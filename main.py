import io
import logging
import os
from contextlib import asynccontextmanager

import numpy as np
import tensorflow as tf
from PIL import Image, ImageEnhance
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from keras.saving import register_keras_serializable

# =========================================================
# CONFIG
# =========================================================
IMG_SIZE = 256
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
SUPPORTED_FORMATS = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

PHOTO_TO_ART_MODEL_PATH = "model/G_photo_to_art.keras"
ART_TO_PHOTO_MODEL_PATH = "model/F_art_to_photo.keras"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================================================
# CUSTOM LAYER
# =========================================================
@register_keras_serializable()
class InstanceNormalization(tf.keras.layers.Layer):
    def __init__(self, epsilon=1e-5, **kwargs):
        super().__init__(**kwargs)
        self.epsilon = epsilon

    def build(self, input_shape):
        channels = input_shape[-1]
        self.gamma = self.add_weight(
            shape=(channels,),
            initializer="ones",
            trainable=True,
            name="gamma",
        )
        self.beta = self.add_weight(
            shape=(channels,),
            initializer="zeros",
            trainable=True,
            name="beta",
        )

    def call(self, x):
        mean, variance = tf.nn.moments(x, axes=[1, 2], keepdims=True)
        normalized = (x - mean) / tf.sqrt(variance + self.epsilon)
        return self.gamma * normalized + self.beta

    def get_config(self):
        config = super().get_config()
        config.update({"epsilon": self.epsilon})
        return config

# =========================================================
# HELPERS
# =========================================================
def validate_image(file: UploadFile):
    if file.content_type not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Use: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )

    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

def preprocess_image(image: Image.Image) -> tf.Tensor:
    image = image.convert("RGB")
    image = image.resize((IMG_SIZE, IMG_SIZE))
    arr = np.array(image, dtype=np.float32)
    tensor = tf.convert_to_tensor(arr)
    tensor = tf.expand_dims(tensor, axis=0)
    tensor = (tensor / 127.5) - 1.0
    return tensor

def deprocess_image(tensor: tf.Tensor) -> tf.Tensor:
    tensor = (tensor + 1.0) * 127.5
    tensor = tf.clip_by_value(tensor, 0, 255)
    return tf.cast(tensor, tf.uint8)

def enhance_result(image: Image.Image, contrast_factor: float = 1.08, color_factor: float = 1.05) -> Image.Image:
    image = ImageEnhance.Contrast(image).enhance(contrast_factor)
    image = ImageEnhance.Color(image).enhance(color_factor)
    return image

# =========================================================
# GLOBAL MODELS
# =========================================================
models = {}

# =========================================================
# LIFESPAN
# =========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup...")

    try:
        logger.info("Loading GAN generators...")

        custom_objects = {"InstanceNormalization": InstanceNormalization}

        models["photo_to_art"] = tf.keras.models.load_model(
            PHOTO_TO_ART_MODEL_PATH,
            custom_objects=custom_objects,
            compile=False,
        )

        models["art_to_photo"] = tf.keras.models.load_model(
            ART_TO_PHOTO_MODEL_PATH,
            custom_objects=custom_objects,
            compile=False,
        )

        logger.info("✅ Both generators loaded successfully.")
    except Exception as e:
        logger.exception("❌ Error loading models: %s", e)
        models.clear()

    yield

    logger.info("Application shutdown.")

# =========================================================
# APP
# =========================================================
app = FastAPI(
    title="Bidirectional GAN Image Translation API",
    version="7.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static")

# =========================================================
# ROUTES
# =========================================================
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "photo_to_art_loaded": "photo_to_art" in models,
        "art_to_photo_loaded": "art_to_photo" in models,
    }

@app.post("/transform/")
async def transform_image(
    content_file: UploadFile = File(...),
    direction: str = Form(...),
):
    """
    direction:
      - photo_to_art
      - art_to_photo
    """
    if "photo_to_art" not in models or "art_to_photo" not in models:
        raise HTTPException(status_code=503, detail="Models are not loaded.")

    validate_image(content_file)

    if direction not in {"photo_to_art", "art_to_photo"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid direction. Use 'photo_to_art' or 'art_to_photo'.",
        )

    try:
        content_bytes = await content_file.read()
        input_image = Image.open(io.BytesIO(content_bytes))
        input_tensor = preprocess_image(input_image)

        if direction == "photo_to_art":
            output_tensor = models["photo_to_art"](input_tensor, training=False)
            filename_prefix = "art"
        else:
            output_tensor = models["art_to_photo"](input_tensor, training=False)
            filename_prefix = "photo"

        final_image_array = deprocess_image(output_tensor[0])
        final_image = Image.fromarray(final_image_array.numpy())
        final_image = enhance_result(final_image)

        buffer = io.BytesIO()
        final_image.save(buffer, format="JPEG", quality=95)
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="image/jpeg",
            headers={
                "X-Translation-Direction": direction,
                "Content-Disposition": f'inline; filename="{filename_prefix}_result.jpg"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error during transformation")
        raise HTTPException(status_code=500, detail=str(e))
document.addEventListener('DOMContentLoaded', () => {
    const API_BASE = 'http://127.0.0.1:8000';

    const contentFileInput = document.getElementById('contentFile');
    const contentPreviewBox = document.getElementById('contentPreviewBox');
    const submitButton = document.getElementById('submitButton');
    const downloadButton = document.getElementById('downloadButton');
    const directionSelect = document.getElementById('directionSelect');

    const resultPlaceholder = document.getElementById('resultPlaceholder');
    const resultImage = document.getElementById('resultImage');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const errorToast = document.getElementById('error-toast');

    const MAX_SIZE = 10 * 1024 * 1024; // 10MB

    let generatedImageUrl = null;

    function showError(message) {
        errorToast.textContent = message;
        errorToast.classList.add('show');
        setTimeout(() => errorToast.classList.remove('show'), 4000);
    }

    function clearGeneratedImage() {
        if (generatedImageUrl) {
            URL.revokeObjectURL(generatedImageUrl);
            generatedImageUrl = null;
        }
        resultImage.src = '';
        resultImage.classList.remove('visible');
        resultPlaceholder.style.display = 'flex';
        downloadButton.disabled = true;
    }

    function previewImage(file, previewBox) {
        if (!file) return;

        if (file.size > MAX_SIZE) {
            showError('File size exceeds 10MB.');
            contentFileInput.value = '';
            return;
        }

        if (!file.type.startsWith('image/')) {
            showError('Please upload a valid image file.');
            contentFileInput.value = '';
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            previewBox.innerHTML = `<img src="${e.target.result}" alt="Preview">`;
        };
        reader.readAsDataURL(file);

        clearGeneratedImage();
    }

    function setupDragAndDrop(dropZone, fileInput) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'));
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'));
        });

        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                fileInput.files = files;
                previewImage(files[0], dropZone);
            }
        });
    }

    contentFileInput.addEventListener('change', () => {
        previewImage(contentFileInput.files[0], contentPreviewBox);
    });

    setupDragAndDrop(contentPreviewBox, contentFileInput);

    submitButton.addEventListener('click', async (e) => {
        e.preventDefault();

        const file = contentFileInput.files[0];
        if (!file) {
            showError('Please upload an image first.');
            return;
        }

        const direction = directionSelect.value;

        submitButton.disabled = true;
        downloadButton.disabled = true;
        loadingSpinner.classList.add('visible');
        clearGeneratedImage();

        const formData = new FormData();
        formData.append('content_file', file);
        formData.append('direction', direction);

        try {
            const response = await fetch(`${API_BASE}/transform/`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                let errorMessage = 'An unknown server error occurred.';
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorMessage;
                } catch (_) {}
                throw new Error(errorMessage);
            }

            const imageBlob = await response.blob();

            if (generatedImageUrl) {
                URL.revokeObjectURL(generatedImageUrl);
            }

            generatedImageUrl = URL.createObjectURL(imageBlob);

            resultImage.onload = () => {
                resultPlaceholder.style.display = 'none';
                resultImage.classList.add('visible');
            };
            resultImage.src = generatedImageUrl;

            downloadButton.disabled = false;

        } catch (error) {
            showError(`Processing failed: ${error.message}`);
        } finally {
            submitButton.disabled = false;
            loadingSpinner.classList.remove('visible');
        }
    });

    downloadButton.addEventListener('click', () => {
        if (!generatedImageUrl) return;

        const link = document.createElement('a');
        const direction = directionSelect.value;

        link.href = generatedImageUrl;
        link.download = direction === 'photo_to_art'
            ? 'gan_art_result.jpg'
            : 'photo_restoration_result.jpg';

        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    });
});
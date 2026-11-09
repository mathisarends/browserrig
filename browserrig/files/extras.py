from importlib.util import find_spec

_OCR_MODULES = ("rapidocr", "onnxruntime", "cv2", "pypdfium2")

FILES_MISSING = 'Install "browserrig[files]" to read {format} files (missing {module})'
OCR_MISSING = 'Local OCR is not installed; install "browserrig[ocr]" to recognize text'


def ocr_installed() -> bool:
    return all(find_spec(name) is not None for name in _OCR_MODULES)

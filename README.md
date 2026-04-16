# 🪙 altaycoins Coin Imaging Suite

A lightweight, purely web-based image processing application built with [Streamlit](https://altaycoins.streamlit.app/). This tool is designed specifically for numismatists, coin collectors, and photographers to easily remove backgrounds, stitch, crop, edit, and enhance coin photography without needing complex desktop software.

## ✨ Features

The application features a global format selector (toggling between transparent PNGs and white-background JPEGs) and includes the following 8 processing tools:

* **✨ Remover:** Automatically removes the background from coin images using AI (`rembg`).
* **🧩 Stitcher:** Stitches obverse (front) and reverse (back) images together horizontally into a single image.
* **🔪 Splitter:** Slices a stitched coin image back into two separate obverse and reverse files.
* **🔄 Swapper:** Swaps the left and right sides of an already stitched coin image.
* **✂️ Cropper:** Manually crop images using freeform or fixed aspect ratios (1:1, 16:9, etc.).
* **🎨 Corrector:** Adjust tone, brightness, contrast, sharpness, and color saturation.
* **💧 Watermarker:** Overlay a custom PNG watermark onto your images with adjustable scale, opacity, and positioning.
* **🔍 Enhancer:** Apply a quick sharpening filter to bring out fine details in the coin's relief.

All tools support bulk processing (uploading multiple files at once) and offer **ZIP batch downloading** for the processed results.

## 🛠️ Installation & Local Usage

To run this application locally on your computer, follow these steps:

**1. Clone the repository**
```bash
git clone https://github.com/altaycoins/ImagingSuite.git
cd ImagingSuite
```
**2. Create a virtual environment**
It is highly recommended to use a virtual environment to manage dependencies.

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac/Linux
python3 -m venv .venv
source .venv/bin/activate
```
**3. Install dependencies**

```bash
pip install -r requirements.txt
```
**4. Run the application**

```Bash
streamlit run ImagingSuite.py
```
Note: Make sure your main python file is named ImagingSuite.py. If it is named differently, replace ImagingSuite.py with your file name.

📦 Requirements

```
streamlit
streamlit-cropper
Pillow
rembg
```


📄 License
Copyright (c) 2026 altaycoins.com  All rights reserved.
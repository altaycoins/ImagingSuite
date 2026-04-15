import streamlit as st
from PIL import Image, ImageEnhance
import io
import os
import zipfile

try:
    from rembg import remove
    from streamlit_cropper import st_cropper
except ImportError as e:
    st.error(f"A required library is missing. Please install it. Error: {e}")
    st.stop()

TOOL_PAGES = {
    'remover': "✨ Remover",
    'stitcher': "🧩 Stitcher",
    'splitter': "🔪 Splitter",
    'swapper': "🔄 Swapper",
    'cropper': "✂️ Cropper",
    'corrector': "🎨 Corrector",
    'watermarker': "💧 Watermarker",
    'enhancer': "🔍 Enhancer"
}

TOOL_INFO = {
    'remover': "Automatically remove the background from images using AI.",
    'stitcher': "Stitch coin sides together horizontally. Upload images in pairs.",
    'splitter': "Split stitched images into two separate files (e.g., obverse and reverse).",
    'swapper': "Swap the obverse and reverse sides of a coin image.",
    'cropper': "Manually crop your images. Choose an aspect ratio or crop freely.",
    'corrector': "Adjust brightness, contrast, and other color properties for all images at once.",
    'watermarker': "Apply a watermark to a batch of photos.",
    'enhancer': "Apply a sharpening filter to bring out fine details."
}

def info_box(text):
    st.markdown(f'<div style="background-color: #e6f3ff; border-left: 5px solid #0066cc; padding: 10px; border-radius: 5px; margin-bottom: 1rem;">{text}</div>', unsafe_allow_html=True)

def composite_on_white(img):
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.convert('RGBA').getchannel('A'))
        return background
    else:
        return img.convert('RGB')

def get_file_meta(base_name, suffix=""):
    fmt = st.session_state.get('global_format', 'PNG')
    ext = "jpg" if fmt == "JPEG" else "png"
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    filename = f"{base_name}_{suffix}.{ext}" if suffix else f"{base_name}.{ext}"
    return filename, mime, fmt

def get_download_data(img):
    fmt = st.session_state.get('global_format', 'PNG')
    img_to_save = img if fmt == 'PNG' else composite_on_white(img)
    buf = io.BytesIO()
    img_to_save.save(buf, format=fmt, quality=100)
    return buf.getvalue()

def create_zip_download_button(processed_items, zip_filename_base, default_suffix=""):
    if not processed_items or len(processed_items) <= 1: return
    st.divider()
    st.subheader("Download All Together")
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for item in processed_items:
            # Handle standard tuples (base_name, img) or splitter tuples (base_name, img, suffix)
            if len(item) == 3:
                base_name, img, suffix = item
            else:
                base_name, img = item
                suffix = default_suffix
            
            filename, _, fmt = get_file_meta(base_name, suffix)
            img_to_save = img if fmt == 'PNG' else composite_on_white(img)
                 
            img_byte_arr = io.BytesIO()
            img_to_save.save(img_byte_arr, format=fmt, quality=100)
            zipf.writestr(filename, img_byte_arr.getvalue())
            
    st.download_button(
        label="📦 Download All as ZIP",
        data=zip_buffer.getvalue(),
        file_name=f"{zip_filename_base}.zip",
        mime="application/zip",
        width='stretch'
    )

##### MAIN LOGIC FILES HERE ###

def swapper_logic(files):
    def _run_swap(idx):
        item = st.session_state.swapper_results[idx]
        slider_key = item['file_ref'].file_id
        mid = st.session_state[slider_key]
        
        image = item['original']
        w, h = image.size
        
        obv, rev = image.crop((0, 0, mid, h)), image.crop((mid, 0, w, h))

        new_img = Image.new("RGB", (w, h), color='white')
        new_img.paste(rev, (0, 0), rev if 'A' in rev.getbands() else None)
        new_img.paste(obv, (rev.width, 0), obv if 'A' in obv.getbands() else None)
        
        st.session_state.swapper_results[idx]['processed'] = new_img

    current_files_id = [f.file_id for f in files] if files else None
    if 'swapper_id' in st.session_state and st.session_state.swapper_id != current_files_id:
        if 'swapper_results' in st.session_state: del st.session_state.swapper_results
        if 'swapper_id' in st.session_state: del st.session_state.swapper_id

    if files and 'swapper_results' not in st.session_state:
        processed_images = []
        for f in files:
            image = Image.open(f) 
            base, _ = os.path.splitext(f.name)
            
            w, h = image.size
            mid_default = w // 2
            obv_default, rev_default = image.crop((0, 0, mid_default, h)), image.crop((mid_default, 0, w, h))
            new_img_default = Image.new("RGB", (w, h), color='white')
            new_img_default.paste(rev_default, (0, 0), rev_default if 'A' in rev_default.getbands() else None)
            new_img_default.paste(obv_default, (rev_default.width, 0), obv_default if 'A' in obv_default.getbands() else None)

            processed_images.append({
                'original': image, 
                'processed': new_img_default,
                'base_name': base, 
                'file_ref': f
            })
            
        st.session_state.swapper_results = processed_images
        st.session_state.swapper_id = current_files_id

    if 'swapper_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_swapper"):
            del st.session_state.swapper_results
            del st.session_state.swapper_id
            st.rerun()

        for idx, item in enumerate(st.session_state.swapper_results):
            image = item['original']
            processed_image = item['processed'] 
            base = item['base_name']
            w, h = image.size
            
            filename, mime, fmt = get_file_meta(base, "swapped")
            st.write(f"**Processing:** `{base}`")
            
            mid = st.slider(
                "Adjust split point", 1, w - 1, w // 2, 
                key=item['file_ref'].file_id,
                on_change=_run_swap,
                args=(idx,)
            )
            
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.image(image, caption="Original", width='stretch') 
            col2.image(processed_image, caption="Swapped", width='stretch')

            img_data = get_download_data(processed_image)
            col3.download_button(
                label="Download", 
                data=img_data, 
                file_name=filename, 
                mime=mime,
                key=f"download_{base}"
            )
            st.divider()
            
        final_processed = [(item['base_name'], item['processed']) for item in st.session_state.swapper_results if item['processed']]
        create_zip_download_button(final_processed, "swapped_coins", "swapped")

def stitcher_logic(files):
    if len(files) % 2 != 0:
        st.warning("Please upload an even number of images to create pairs."); return
    files.sort(key=lambda f: f.name)
    resize_option = st.radio("Resizing Option", ["Make smaller image match larger", "Make larger image match smaller"], horizontal=True)
    pairs = [(files[i], files[i+1]) for i in range(0, len(files), 2)]
    st.subheader("Image Pairs")
    for i, (f1, f2) in enumerate(pairs):
        st.write(f"**Pair {i+1}:** `{f1.name}` & `{f2.name}`")
        c1, c2 = st.columns(2); c1.image(f1, width='stretch'); c2.image(f2, width='stretch')
        st.divider()
    if st.button("Process All Pairs", width='stretch', type="primary"):
        processed_images = []
        with st.spinner("Stitching images..."):
            for f1, f2 in pairs:
                img1 = composite_on_white(Image.open(f1))
                img2 = composite_on_white(Image.open(f2))

                h1, h2 = img1.height, img2.height
                target_h = max(h1, h2) if resize_option.startswith("Make smaller") else min(h1, h2)
                if img1.height != target_h: img1 = img1.resize((int(img1.width * target_h / h1), target_h), Image.Resampling.LANCZOS)
                if img2.height != target_h: img2 = img2.resize((int(img2.width * target_h / h2), target_h), Image.Resampling.LANCZOS)
                
                stitched = Image.new("RGB", (img1.width + img2.width, target_h))
                stitched.paste(img1, (0,0)); stitched.paste(img2, (img1.width, 0))
                base, _ = os.path.splitext(f1.name)
                processed_images.append((base, stitched))
        st.session_state.stitcher_results = processed_images

    if 'stitcher_results' in st.session_state:
        st.success("Processing complete! View your results below.")
        st.subheader("Stitched Images")
        if st.button("Clear Results", key="clear_stitcher"):
            del st.session_state.stitcher_results
            st.rerun()
        for base, img in st.session_state.stitcher_results:
            filename, mime, _ = get_file_meta(base, "stitched")
            col1, col2 = st.columns([3, 1])
            col1.image(img, caption=filename, width='stretch')
            img_data = get_download_data(img)
            col2.download_button(label="Download", data=img_data, file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()
        create_zip_download_button(st.session_state.stitcher_results, "stitched_coins", "stitched")

def splitter_logic(files):
    def _run_split(idx):
        item = st.session_state.splitter_results[idx]
        slider_key = item['file_ref'].file_id
        mid = st.session_state[slider_key]
        
        image = item['original']
        w, h = image.size
        
        part_a = image.crop((0, 0, mid, h))
        part_b = image.crop((mid, 0, w, h))

        st.session_state.splitter_results[idx]['processed_a'] = part_a
        st.session_state.splitter_results[idx]['processed_b'] = part_b

    current_files_id = [f.file_id for f in files] if files else None

    if 'splitter_id' in st.session_state and st.session_state.splitter_id != current_files_id:
        if 'splitter_results' in st.session_state: del st.session_state.splitter_results
        if 'splitter_id' in st.session_state: del st.session_state.splitter_id

    if files and 'splitter_results' not in st.session_state:
        processed_images = []
        for f in files:
            image = Image.open(f)
            base, _ = os.path.splitext(f.name)
            
            w, h = image.size
            mid_default = w // 2

            part_a_default = image.crop((0, 0, mid_default, h))
            part_b_default = image.crop((mid_default, 0, w, h))

            processed_images.append({
                'original': image,
                'processed_a': part_a_default,
                'processed_b': part_b_default, 
                'base_name': base,
                'file_ref': f
            })
            
        st.session_state.splitter_results = processed_images
        st.session_state.splitter_id = current_files_id

    if 'splitter_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_splitter"):
            del st.session_state.splitter_results
            del st.session_state.splitter_id
            st.rerun()

        for idx, item in enumerate(st.session_state.splitter_results):
            original_image = item['original']
            part_a = item['processed_a'] 
            part_b = item['processed_b'] 
            base = item['base_name']
            w, h = original_image.size
            
            filename_a, mime_a, _ = get_file_meta(base, "a")
            filename_b, mime_b, _ = get_file_meta(base, "b")
            
            st.write(f"**Processing:** `{base}`")
            
            st.slider(
                "Adjust split point", 1, w - 1, w // 2,
                key=item['file_ref'].file_id,
                on_change=_run_split, 
                args=(idx,)
            )
            
            st.image(original_image, caption="Original", width='stretch')
            
            col1, col2 = st.columns(2)
            with col1:
                st.image(part_a, caption=filename_a, width='stretch')
                img_data_a = get_download_data(part_a)
                st.download_button(
                    label=f"Download {filename_a}",
                    data=img_data_a,
                    file_name=filename_a,
                    mime=mime_a,
                    width='stretch',
                    key=f"download_a_{base}"
                )
            with col2:
                st.image(part_b, caption=filename_b, width='stretch')
                img_data_b = get_download_data(part_b)
                st.download_button(
                    label=f"Download {filename_b}",
                    data=img_data_b,
                    file_name=filename_b,
                    mime=mime_b,
                    width='stretch',
                    key=f"download_b_{base}"
                )
            st.divider()
            
        final_processed = []
        for item in st.session_state.splitter_results:
            if item['processed_a']:
                final_processed.append((item['base_name'], item['processed_a'], "a"))
            if item['processed_b']:
                final_processed.append((item['base_name'], item['processed_b'], "b"))
        
        create_zip_download_button(final_processed, "split_coins")

def remover_logic(files):
    current_files_id = [f.file_id for f in files] if files else None
    if 'remover_id' in st.session_state and st.session_state.remover_id != current_files_id:
        if 'remover_results' in st.session_state: del st.session_state.remover_results
        if 'remover_id' in st.session_state: del st.session_state.remover_id
        
    if files and 'remover_results' not in st.session_state:
        st.subheader("Processing...")
        progress_bar = st.progress(0, "Starting background removal...")
        processed_images = []
        for i, f in enumerate(files):
            progress_bar.progress((i) / len(files), f"Processing {f.name}...")
            original_image = Image.open(f)
            output_bytes = remove(f.getvalue())
            result_image = Image.open(io.BytesIO(output_bytes))
            base, _ = os.path.splitext(f.name)
            processed_images.append({'original': original_image, 'processed': result_image, 'base_name': base})
        progress_bar.empty()
        st.session_state.remover_results = processed_images
        st.session_state.remover_id = current_files_id

    if 'remover_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_remover"):
            del st.session_state.remover_results
            del st.session_state.remover_id
            st.rerun()
            
        for item in st.session_state.remover_results:
            base = item['base_name']
            filename, mime, _ = get_file_meta(base, "no-bg")
            
            st.write(f"**File:** `{base}`")
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.image(item['original'], caption="Original", width='stretch')
            col2.image(item['processed'], caption="Background Removed", width='stretch')
            
            img_data = get_download_data(item['processed'])
            col3.download_button(label="Download", data=img_data, file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()
            
        final_processed = [(item['base_name'], item['processed']) for item in st.session_state.remover_results]
        create_zip_download_button(final_processed, "removed_bg", "no-bg")

def cropper_logic(files):
    if len(files) > 1:
        file_to_crop = st.selectbox("Choose an image to crop", options=[f.name for f in files])
        img_file = next((f for f in files if f.name == file_to_crop), files[0])
    else:
        img_file = files[0]
        
    original_image = Image.open(img_file)
    aspect_ratios = {"Free": None, "1:1": (1,1), "16:9": (16,9), "4:3": (4,3), "3:2": (3,2), "9:16": (9,16), "3:4": (3,4), "2:3": (2,3)}
    aspect_choice = st.selectbox("Aspect Ratio:", options=list(aspect_ratios.keys()))
    st.info("Drag the corners of the box to crop your image.")
    
    cropped_img = st_cropper(original_image, realtime_update=True, aspect_ratio=aspect_ratios[aspect_choice], key=f'cropper_{img_file.name}')
    st.subheader("Cropped Result")
    st.image(cropped_img, width='stretch')
    
    base, _ = os.path.splitext(img_file.name)
    filename, mime, _ = get_file_meta(base, "cropped")
    img_data = get_download_data(cropped_img)
    st.download_button(label=f"⬇️ Download Cropped Image", data=img_data, file_name=filename, mime=mime, width='stretch')

def corrector_logic(files):
    st.subheader("Correction Settings")
    st.write("**White Balance**")
    temperature = st.slider("Temperature (Blue ↔️ Yellow)", -100, 100, 0)
    tint = st.slider("Tint (Green ↔️ Magenta)", -100, 100, 0)
    st.write("---")
    st.write("**Tone & Detail**")
    brightness = st.slider("Brightness", 0.5, 1.5, 1.0)
    contrast = st.slider("Contrast", 0.5, 1.5, 1.0)
    sharpness = st.slider("Sharpness", 0.0, 3.0, 1.0)
    saturation = st.slider("Saturation (Color)", 0.0, 2.0, 1.0)
    
    def apply_corrections(img):
        img = composite_on_white(img)
        corrected = ImageEnhance.Brightness(img).enhance(brightness)
        corrected = ImageEnhance.Contrast(corrected).enhance(contrast)
        corrected = ImageEnhance.Sharpness(corrected).enhance(sharpness)
        corrected = ImageEnhance.Color(corrected).enhance(saturation)
        return corrected

    if st.button("Apply Corrections", width='stretch', type="primary"):
        processed_images = []
        with st.spinner("Processing all images..."):
            for f in files:
                original_image = Image.open(f)
                result_image = apply_corrections(original_image)
                base, _ = os.path.splitext(f.name)
                processed_images.append((base, result_image))
        st.session_state.corrector_results = processed_images
        st.session_state.corrector_files_id = [f.file_id for f in files]
        st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'corrector_files_id' in st.session_state and st.session_state.corrector_files_id != current_files_id:
        if 'corrector_results' in st.session_state: del st.session_state.corrector_results
        if 'corrector_files_id' in st.session_state: del st.session_state.corrector_files_id

    if 'corrector_results' in st.session_state:
        st.subheader("Result")
        processed_images = st.session_state.corrector_results
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            
            base, img = processed_images[0]
            filename, mime, _ = get_file_meta(base, "corrected")
            img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown below.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            create_zip_download_button(processed_images, "corrected_images", "corrected")

def watermarker_logic(files):
    st.subheader("Watermark Settings")
    watermark_file = st.file_uploader("Upload your watermark image (PNG recommended)", type=["png"])
    
    if watermark_file:
        watermark_img = Image.open(watermark_file).convert("RGBA")
        pos_map = {"Center": (0.5, 0.5), "Top Left": (0, 0), "Top Right": (1, 0), "Bottom Left": (0, 1), "Bottom Right": (1, 1)}
        c1, c2, c3 = st.columns(3)
        pos = c1.selectbox("Position", list(pos_map.keys()))
        scale = c2.slider("Scale", 10, 100, 25)
        opacity = c3.slider("Opacity", 0, 100, 50)
        
        def apply_watermark(original):
            original = original.convert("RGBA")
            wm_w, wm_h = watermark_img.size
            base_w = int(original.width * (scale / 100))
            wm_resized = watermark_img.resize((base_w, int(wm_h * base_w / wm_w)), Image.Resampling.LANCZOS)
            if opacity < 100:
                alpha = wm_resized.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(opacity / 100)
                wm_resized.putalpha(alpha)
            px, py = pos_map[pos]
            pos_x = int(original.width * px - wm_resized.width * px)
            pos_y = int(original.height * py - wm_resized.height * py)
            transparent = Image.new('RGBA', original.size, (0,0,0,0)); transparent.paste(original, (0,0)); transparent.paste(wm_resized, (pos_x, pos_y), mask=wm_resized)
            
            # Use format-aware saving instead of forcing composite on white here
            return transparent

        if st.button("Apply Watermark", width='stretch', type="primary"):
            processed_images = []
            with st.spinner("Processing all images..."):
                for f in files:
                    original_image = Image.open(f)
                    result_image = apply_watermark(original_image)
                    base, _ = os.path.splitext(f.name)
                    processed_images.append((base, result_image))
            st.session_state.watermarker_results = processed_images
            st.session_state.watermarker_files_id = [f.file_id for f in files]
            st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'watermarker_files_id' in st.session_state and st.session_state.watermarker_files_id != current_files_id:
        if 'watermarker_results' in st.session_state: del st.session_state.watermarker_results
        if 'watermarker_files_id' in st.session_state: del st.session_state.watermarker_files_id

    if 'watermarker_results' in st.session_state:
        st.subheader("Result")
        processed_images = st.session_state.watermarker_results
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            
            base, img = processed_images[0]
            filename, mime, _ = get_file_meta(base, "watermarked")
            img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown below.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            create_zip_download_button(processed_images, "watermarked_images", "watermarked")

def enhancer_logic(files):
    st.subheader("Enhancement Settings")
    sharpness = st.slider("Sharpness Level", 1.0, 5.0, 2.0, 0.1)
    
    def apply_enhancement(img):
        img_rgb = composite_on_white(img)
        return ImageEnhance.Sharpness(img_rgb).enhance(sharpness)

    if st.button("Apply Enhancement", width='stretch', type="primary"):
        processed_images = []
        with st.spinner("Processing all images..."):
            for f in files:
                original_image = Image.open(f)
                result_image = apply_enhancement(original_image)
                base, _ = os.path.splitext(f.name)
                processed_images.append((base, result_image))
        st.session_state.enhancer_results = processed_images
        st.session_state.enhancer_files_id = [f.file_id for f in files]
        st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'enhancer_files_id' in st.session_state and st.session_state.enhancer_files_id != current_files_id:
        if 'enhancer_results' in st.session_state: del st.session_state.enhancer_results
        if 'enhancer_files_id' in st.session_state: del st.session_state.enhancer_files_id

    if 'enhancer_results' in st.session_state:
        st.subheader("Result")
        processed_images = st.session_state.enhancer_results
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            
            base, img = processed_images[0]
            filename, mime, _ = get_file_meta(base, "enhanced")
            img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown below.")
            col1, col2 = st.columns(2)
            col1.image(Image.open(files[0]), caption="Original", width='stretch')
            col2.image(processed_images[0][1], caption="Processed", width='stretch')
            create_zip_download_button(processed_images, "enhanced_images", "enhanced")

# --- MAIN APP LAYOUT ---
st.set_page_config(page_title="altaycoins Coin Imaging Suite", layout="centered", initial_sidebar_state="expanded")

with st.sidebar:
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path)
    st.divider()
    
    st.session_state.global_format = st.selectbox(
        "Download Format", 
        options=["PNG", "JPEG"], 
        format_func=lambda x: "PNG (Supports Transparency)" if x == "PNG" else "JPG (Composited on White)"
    )
    st.divider()
    
    if 'view' not in st.session_state:
        st.session_state.view = 'remover'
        
    for page_key, display_name in TOOL_PAGES.items():
        st.button(
            display_name,
            key=f"btn_{page_key}",
            width='stretch',
            type="primary" if st.session_state.view == page_key else "secondary",
            on_click=lambda key=page_key: st.session_state.update(view=key)
        )

tool_logic_map = {
    'remover': remover_logic,
    'stitcher': stitcher_logic,
    'splitter': splitter_logic, 
    'swapper': swapper_logic,
    'cropper': cropper_logic,
    'corrector': corrector_logic,
    'watermarker': watermarker_logic,
    'enhancer': enhancer_logic
}

current_view = st.session_state.get('view', 'remover')
tool_function = tool_logic_map.get(current_view)

if tool_function:
    st.title(TOOL_PAGES[current_view])
    if current_view in TOOL_INFO:
         info_box(TOOL_INFO[current_view])

    if 'last_view' not in st.session_state or st.session_state.last_view != current_view:
        keys_to_clear = [
            'remover_results', 'stitcher_results', 'swapper_results', 'splitter_results', 
            'remover_id', 'swapper_id', 'splitter_id', 'corrector_results', 'corrector_files_id', 
            'watermarker_results', 'watermarker_files_id', 'enhancer_results', 'enhancer_files_id'
        ]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
    st.session_state.last_view = current_view
    
    uploaded_files = st.file_uploader(
        "Upload your image(s)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=current_view
    )
    if uploaded_files:
        tool_function(uploaded_files)
else:
    st.session_state.view = 'remover'
    st.rerun()
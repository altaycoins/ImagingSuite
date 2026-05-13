import streamlit as st
from PIL import Image, ImageEnhance
import io
import os
import re
import zipfile
import tempfile
import shutil
import gc
import sqlite3
import pandas as pd

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
    'enhancer': "🔍 Enhancer",
    'stats': "📊 Statistics"
}

TOOL_INFO = {
    'remover': "Automatically remove the background from images using AI. Auto-crops and stitches multi-side coins.",
    'stitcher': "Stitch coin sides together horizontally. Upload images in pairs.",
    'splitter': "Split stitched images into two separate files (e.g., obverse and reverse).",
    'swapper': "Swap the obverse and reverse sides of a coin image.",
    'cropper': "Manually crop your images. Choose an aspect ratio or crop freely.",
    'corrector': "Adjust brightness, contrast, and other color properties for all images at once.",
    'watermarker': "Apply a watermark to a batch of photos.",
    'enhancer': "Apply a sharpening filter to bring out fine details."
}

# --- DATABASE MANAGEMENT HELPERS ---

DB_FILE = "usage_stats.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (tool_name TEXT PRIMARY KEY, uses INTEGER, images_processed INTEGER)''')
    conn.commit()
    conn.close()

def update_stats(tool_name, num_images):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO stats (tool_name, uses, images_processed) 
                 VALUES (?, 1, ?)
                 ON CONFLICT(tool_name) DO UPDATE SET 
                 uses = uses + 1, 
                 images_processed = images_processed + ?''', 
              (tool_name, num_images, num_images))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM stats ORDER BY uses DESC", conn)
    conn.close()
    return df

# Initialize DB on load
init_db()


# --- DISK MEMORY MANAGEMENT HELPERS ---

def init_temp_dir():
    if 'temp_dir' not in st.session_state:
        st.session_state.temp_dir = tempfile.mkdtemp()
    
    # Force the directory to exist right now, just in case the cloud OS wiped it
    os.makedirs(st.session_state.temp_dir, exist_ok=True)
    return st.session_state.temp_dir

def cleanup_temp_dir():
    if 'temp_dir' in st.session_state and os.path.exists(st.session_state.temp_dir):
        shutil.rmtree(st.session_state.temp_dir)
        del st.session_state.temp_dir

def sanitize_filename(name):
    # Removes hidden slashes, newlines, or illegal path characters
    return re.sub(r'[\\/*?:"<>|\n\r]', "", name)

# ----------------------------------------

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
    fmt = st.session_state.get('global_format', 'JPEG') 
    ext = "jpg" if fmt == "JPEG" else "png"
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    filename = f"{base_name}_{suffix}.{ext}" if suffix else f"{base_name}.{ext}"
    return filename, mime, fmt

def get_download_data(img):
    fmt = st.session_state.get('global_format', 'JPEG')
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
            if len(item) == 3:
                base_name, img_source, suffix = item
            else:
                base_name, img_source = item
                suffix = default_suffix
            
            filename, _, fmt = get_file_meta(base_name, suffix)
            
            img = Image.open(img_source) if isinstance(img_source, str) else img_source
            img_to_save = img if fmt == 'PNG' else composite_on_white(img)
                  
            img_byte_arr = io.BytesIO()
            img_to_save.save(img_byte_arr, format=fmt, quality=100)
            zipf.writestr(filename, img_byte_arr.getvalue())
            
            if isinstance(img_source, str):
                img.close()
            
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
        
        item['file_ref'].seek(0)
        with Image.open(item['file_ref']) as image:
            w, h = image.size
            obv, rev = image.crop((0, 0, mid, h)), image.crop((mid, 0, w, h))
            new_img = Image.new("RGB", (w, h), color='white')
            new_img.paste(rev, (0, 0), rev if 'A' in rev.getbands() else None)
            new_img.paste(obv, (rev.width, 0), obv if 'A' in obv.getbands() else None)
            new_img.save(item['processed_path'], format="PNG")
            
        gc.collect()

    current_files_id = [f.file_id for f in files] if files else None
    if 'swapper_id' in st.session_state and st.session_state.swapper_id != current_files_id:
        if 'swapper_results' in st.session_state: del st.session_state.swapper_results
        if 'swapper_id' in st.session_state: del st.session_state.swapper_id

    if files and 'swapper_results' not in st.session_state:
        temp_dir = init_temp_dir()
        processed_images = []
        for f in files:
            f.seek(0)
            with Image.open(f) as image:
                base, _ = os.path.splitext(f.name)
                w, h = image.size
                mid_default = w // 2
                obv_default, rev_default = image.crop((0, 0, mid_default, h)), image.crop((mid_default, 0, w, h))
                new_img_default = Image.new("RGB", (w, h), color='white')
                new_img_default.paste(rev_default, (0, 0), rev_default if 'A' in rev_default.getbands() else None)
                new_img_default.paste(obv_default, (rev_default.width, 0), obv_default if 'A' in obv_default.getbands() else None)

                temp_path = os.path.join(temp_dir, f"{base}_swapped.png")
                new_img_default.save(temp_path, format="PNG")

                processed_images.append({
                    'processed_path': temp_path,
                    'base_name': base, 
                    'file_ref': f
                })
        
        update_stats('swapper', len(files))
        gc.collect()    
        st.session_state.swapper_results = processed_images
        st.session_state.swapper_id = current_files_id

    if 'swapper_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_swapper"):
            cleanup_temp_dir()
            del st.session_state.swapper_results
            del st.session_state.swapper_id
            st.rerun()

        for idx, item in enumerate(st.session_state.swapper_results):
            base = item['base_name']
            item['file_ref'].seek(0)
            original_image = Image.open(item['file_ref'])
            w, h = original_image.size
            
            filename, mime, fmt = get_file_meta(base, "swapped")
            st.write(f"**Processing:** `{base}`")
            
            mid = st.slider(
                "Adjust split point", 1, w - 1, w // 2, 
                key=item['file_ref'].file_id,
                on_change=_run_swap,
                args=(idx,)
            )
            
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.image(original_image, caption="Original", width='stretch') 
            col2.image(item['processed_path'], caption="Swapped", width='stretch')

            with Image.open(item['processed_path']) as img:
                img_data = get_download_data(img)
            col3.download_button(
                label="Download", 
                data=img_data, 
                file_name=filename, 
                mime=mime,
                key=f"download_{base}"
            )
            st.divider()
            
        final_processed = [(item['base_name'], item['processed_path']) for item in st.session_state.swapper_results]
        create_zip_download_button(final_processed, "swapped_coins", "swapped")

def stitcher_logic(files):
    if len(files) % 2 != 0:
        st.warning("Please upload an even number of images to create pairs."); return
    files.sort(key=lambda f: f.name)
    resize_option = st.radio("Resizing Option", ["Make smaller image match larger", "Make larger image match smaller"], index=1, horizontal=True)
    pairs = [(files[i], files[i+1]) for i in range(0, len(files), 2)]
    st.subheader("Image Pairs")
    for i, (f1, f2) in enumerate(pairs):
        st.write(f"**Pair {i+1}:** `{f1.name}` & `{f2.name}`")
        c1, c2 = st.columns(2); c1.image(f1, width='stretch'); c2.image(f2, width='stretch')
        st.divider()
        
    if st.button("Process All Pairs", width='stretch', type="primary"):
        temp_dir = init_temp_dir()
        processed_images = []
        with st.spinner("Stitching images..."):
            for f1, f2 in pairs:
                f1.seek(0); f2.seek(0)
                with Image.open(f1) as open1, Image.open(f2) as open2:
                    img1 = composite_on_white(open1)
                    img2 = composite_on_white(open2)

                    h1, h2 = img1.height, img2.height
                    target_h = max(h1, h2) if resize_option.startswith("Make smaller") else min(h1, h2)
                    if img1.height != target_h: img1 = img1.resize((int(img1.width * target_h / h1), target_h), Image.Resampling.LANCZOS)
                    if img2.height != target_h: img2 = img2.resize((int(img2.width * target_h / h2), target_h), Image.Resampling.LANCZOS)
                    
                    stitched = Image.new("RGB", (img1.width + img2.width, target_h))
                    stitched.paste(img1, (0,0)); stitched.paste(img2, (img1.width, 0))
                    
                    base, _ = os.path.splitext(f1.name)
                    temp_path = os.path.join(temp_dir, f"{base}_stitched.png")
                    stitched.save(temp_path, format="PNG")
                    processed_images.append((base, temp_path))
                    
                gc.collect()
            update_stats('stitcher', len(files))
        st.session_state.stitcher_results = processed_images

    if 'stitcher_results' in st.session_state:
        st.success("Processing complete! View your results below.")
        st.subheader("Stitched Images")
        if st.button("Clear Results", key="clear_stitcher"):
            cleanup_temp_dir()
            del st.session_state.stitcher_results
            st.rerun()
        for base, path in st.session_state.stitcher_results:
            filename, mime, _ = get_file_meta(base, "stitched")
            col1, col2 = st.columns([3, 1])
            col1.image(path, caption=filename, width='stretch')
            
            with Image.open(path) as img:
                img_data = get_download_data(img)
            col2.download_button(label="Download", data=img_data, file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()
        create_zip_download_button(st.session_state.stitcher_results, "stitched_coins", "stitched")

def splitter_logic(files):
    def _run_split(idx):
        item = st.session_state.splitter_results[idx]
        slider_key = item['file_ref'].file_id
        mid = st.session_state[slider_key]
        
        item['file_ref'].seek(0)
        with Image.open(item['file_ref']) as image:
            w, h = image.size
            part_a = image.crop((0, 0, mid, h))
            part_b = image.crop((mid, 0, w, h))

            part_a.save(item['processed_path_a'], format="PNG")
            part_b.save(item['processed_path_b'], format="PNG")
            
        gc.collect()

    current_files_id = [f.file_id for f in files] if files else None

    if 'splitter_id' in st.session_state and st.session_state.splitter_id != current_files_id:
        if 'splitter_results' in st.session_state: del st.session_state.splitter_results
        if 'splitter_id' in st.session_state: del st.session_state.splitter_id

    if files and 'splitter_results' not in st.session_state:
        temp_dir = init_temp_dir()
        processed_images = []
        for f in files:
            f.seek(0)
            with Image.open(f) as image:
                base, _ = os.path.splitext(f.name)
                
                w, h = image.size
                mid_default = w // 2

                part_a_default = image.crop((0, 0, mid_default, h))
                part_b_default = image.crop((mid_default, 0, w, h))

                path_a = os.path.join(temp_dir, f"{base}_a.png")
                path_b = os.path.join(temp_dir, f"{base}_b.png")
                
                part_a_default.save(path_a, format="PNG")
                part_b_default.save(path_b, format="PNG")

                processed_images.append({
                    'processed_path_a': path_a,
                    'processed_path_b': path_b, 
                    'base_name': base,
                    'file_ref': f
                })
        
        update_stats('splitter', len(files))
        gc.collect()
        st.session_state.splitter_results = processed_images
        st.session_state.splitter_id = current_files_id

    if 'splitter_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_splitter"):
            cleanup_temp_dir()
            del st.session_state.splitter_results
            del st.session_state.splitter_id
            st.rerun()

        for idx, item in enumerate(st.session_state.splitter_results):
            item['file_ref'].seek(0)
            original_image = Image.open(item['file_ref'])
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
                st.image(item['processed_path_a'], caption=filename_a, width='stretch')
                with Image.open(item['processed_path_a']) as img_a:
                    img_data_a = get_download_data(img_a)
                st.download_button(
                    label=f"Download {filename_a}", data=img_data_a, file_name=filename_a, mime=mime_a, width='stretch', key=f"download_a_{base}"
                )
            with col2:
                st.image(item['processed_path_b'], caption=filename_b, width='stretch')
                with Image.open(item['processed_path_b']) as img_b:
                    img_data_b = get_download_data(img_b)
                st.download_button(
                    label=f"Download {filename_b}", data=img_data_b, file_name=filename_b, mime=mime_b, width='stretch', key=f"download_b_{base}"
                )
            st.divider()
            
        final_processed = []
        for item in st.session_state.splitter_results:
            final_processed.append((item['base_name'], item['processed_path_a'], "a"))
            final_processed.append((item['base_name'], item['processed_path_b'], "b"))
        
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
        temp_dir = init_temp_dir()
        
        for i, f in enumerate(files):
            progress_bar.progress((i) / len(files), f"Processing {f.name}...")
            
            output_bytes = remove(f.getvalue())
            
            with Image.open(io.BytesIO(output_bytes)) as result_image:
                def get_clean_bbox(img, threshold=20):
                    alpha = img.split()[-1]
                    return alpha.point(lambda p: p if p > threshold else 0).getbbox()

                bbox = get_clean_bbox(result_image)
                final_image = result_image
                
                if bbox:
                    cropped_full = result_image.crop(bbox)
                    w, h = cropped_full.size
                    
                    if w > h * 1.3:
                        mid = w // 2
                        left_side = cropped_full.crop((0, 0, mid, h))
                        right_side = cropped_full.crop((mid, 0, w, h))
                        
                        left_bbox = get_clean_bbox(left_side)
                        right_bbox = get_clean_bbox(right_side)
                        
                        if left_bbox and right_bbox:
                            left_side = left_side.crop(left_bbox)
                            right_side = right_side.crop(right_bbox)
                            
                            target_h = min(left_side.height, right_side.height)
                            
                            if left_side.height != target_h:
                                left_side = left_side.resize((int(left_side.width * target_h / left_side.height), target_h), Image.Resampling.LANCZOS)
                            if right_side.height != target_h:
                                right_side = right_side.resize((int(right_side.width * target_h / right_side.height), target_h), Image.Resampling.LANCZOS)
                            
                            stitched = Image.new("RGBA", (left_side.width + right_side.width, target_h))
                            stitched.paste(left_side, (0, 0))
                            stitched.paste(right_side, (left_side.width, 0))
                            final_image = stitched
                        elif left_bbox:
                            final_image = left_side.crop(left_bbox)
                        elif right_bbox:
                            final_image = right_side.crop(right_bbox)
                        else:
                            final_image = cropped_full
                    else:
                        final_image = cropped_full
                
                base, _ = os.path.splitext(f.name)
                base = sanitize_filename(base) # ADD THIS LINE
                
                temp_path = os.path.join(temp_dir, f"{base}_nobg.png")
                
                os.makedirs(temp_dir, exist_ok=True) # ADD THIS LINE to prevent the Errno 2 crash
                final_image.save(temp_path, format="PNG")
                processed_images.append({'file_ref': f, 'processed_path': temp_path, 'base_name': base})
                
            gc.collect()
            
        progress_bar.empty()
        update_stats('remover', len(files))
        st.session_state.remover_results = processed_images
        st.session_state.remover_id = current_files_id

    if 'remover_results' in st.session_state:
        st.subheader("Results")
        if st.button("Clear Results", key="clear_remover"):
            cleanup_temp_dir()
            del st.session_state.remover_results
            del st.session_state.remover_id
            st.rerun()
            
        for item in st.session_state.remover_results:
            base = item['base_name']
            filename, mime, _ = get_file_meta(base, "no-bg")
            
            st.write(f"**File:** `{base}`")
            col1, col2, col3 = st.columns([2, 2, 1])
            
            item['file_ref'].seek(0)
            col1.image(Image.open(item['file_ref']), caption="Original", width='stretch')
            col2.image(item['processed_path'], caption="Background Removed", width='stretch')
            
            with Image.open(item['processed_path']) as img:
                img_data = get_download_data(img)
                
            col3.download_button(label="Download", data=img_data, file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()
            
        final_processed = [(item['base_name'], item['processed_path']) for item in st.session_state.remover_results]
        create_zip_download_button(final_processed, "removed_bg", "no-bg")

def cropper_logic(files):
    if len(files) > 1:
        file_to_crop = st.selectbox("Choose an image to crop", options=[f.name for f in files])
        img_file = next((f for f in files if f.name == file_to_crop), files[0])
    else:
        img_file = files[0]
        
    if 'cropper_tracked' not in st.session_state or st.session_state.cropper_tracked != img_file.name:
        update_stats('cropper', 1)
        st.session_state.cropper_tracked = img_file.name
        
    img_file.seek(0)
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
        temp_dir = init_temp_dir()
        processed_images = []
        with st.spinner("Processing all images..."):
            for f in files:
                f.seek(0)
                with Image.open(f) as original_image:
                    result_image = apply_corrections(original_image)
                    base, _ = os.path.splitext(f.name)
                    temp_path = os.path.join(temp_dir, f"{base}_corrected.png")
                    result_image.save(temp_path, format="PNG")
                    processed_images.append((base, temp_path))
            gc.collect()
            update_stats('corrector', len(files))
                    
        st.session_state.corrector_results = processed_images
        st.session_state.corrector_files_id = [f.file_id for f in files]
        st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'corrector_files_id' in st.session_state and st.session_state.corrector_files_id != current_files_id:
        if 'corrector_results' in st.session_state: del st.session_state.corrector_results
        if 'corrector_files_id' in st.session_state: del st.session_state.corrector_files_id

    if 'corrector_results' in st.session_state:
        st.subheader("Result")
        if st.button("Clear Results", key="clear_corrector"):
            cleanup_temp_dir()
            del st.session_state.corrector_results
            st.rerun()
            
        processed_images = st.session_state.corrector_results
        
        files[0].seek(0)
        col1, col2 = st.columns(2)
        col1.image(Image.open(files[0]), caption="Original", width='stretch')
        col2.image(processed_images[0][1], caption="Processed", width='stretch')
        
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            base, path = processed_images[0]
            filename, mime, _ = get_file_meta(base, "corrected")
            with Image.open(path) as img:
                img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown above.")
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
            return transparent

        if st.button("Apply Watermark", width='stretch', type="primary"):
            temp_dir = init_temp_dir()
            processed_images = []
            with st.spinner("Processing all images..."):
                for f in files:
                    f.seek(0)
                    with Image.open(f) as original_image:
                        result_image = apply_watermark(original_image)
                        base, _ = os.path.splitext(f.name)
                        temp_path = os.path.join(temp_dir, f"{base}_watermarked.png")
                        result_image.save(temp_path, format="PNG")
                        processed_images.append((base, temp_path))
                gc.collect()
                update_stats('watermarker', len(files))
            st.session_state.watermarker_results = processed_images
            st.session_state.watermarker_files_id = [f.file_id for f in files]
            st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'watermarker_files_id' in st.session_state and st.session_state.watermarker_files_id != current_files_id:
        if 'watermarker_results' in st.session_state: del st.session_state.watermarker_results
        if 'watermarker_files_id' in st.session_state: del st.session_state.watermarker_files_id

    if 'watermarker_results' in st.session_state:
        st.subheader("Result")
        if st.button("Clear Results", key="clear_watermark"):
            cleanup_temp_dir()
            del st.session_state.watermarker_results
            st.rerun()
            
        processed_images = st.session_state.watermarker_results
        
        files[0].seek(0)
        col1, col2 = st.columns(2)
        col1.image(Image.open(files[0]), caption="Original", width='stretch')
        col2.image(processed_images[0][1], caption="Processed", width='stretch')
        
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            base, path = processed_images[0]
            filename, mime, _ = get_file_meta(base, "watermarked")
            with Image.open(path) as img:
                img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown above.")
            create_zip_download_button(processed_images, "watermarked_images", "watermarked")

def enhancer_logic(files):
    st.subheader("Enhancement Settings")
    sharpness = st.slider("Sharpness Level", 1.0, 5.0, 2.0, 0.1)
    
    def apply_enhancement(img):
        img_rgb = composite_on_white(img)
        return ImageEnhance.Sharpness(img_rgb).enhance(sharpness)

    if st.button("Apply Enhancement", width='stretch', type="primary"):
        temp_dir = init_temp_dir()
        processed_images = []
        with st.spinner("Processing all images..."):
            for f in files:
                f.seek(0)
                with Image.open(f) as original_image:
                    result_image = apply_enhancement(original_image)
                    base, _ = os.path.splitext(f.name)
                    temp_path = os.path.join(temp_dir, f"{base}_enhanced.png")
                    result_image.save(temp_path, format="PNG")
                    processed_images.append((base, temp_path))
            gc.collect()
            update_stats('enhancer', len(files))
        st.session_state.enhancer_results = processed_images
        st.session_state.enhancer_files_id = [f.file_id for f in files]
        st.rerun()

    current_files_id = [f.file_id for f in files] if files else None
    if 'enhancer_files_id' in st.session_state and st.session_state.enhancer_files_id != current_files_id:
        if 'enhancer_results' in st.session_state: del st.session_state.enhancer_results
        if 'enhancer_files_id' in st.session_state: del st.session_state.enhancer_files_id

    if 'enhancer_results' in st.session_state:
        st.subheader("Result")
        if st.button("Clear Results", key="clear_enhancer"):
            cleanup_temp_dir()
            del st.session_state.enhancer_results
            st.rerun()
            
        processed_images = st.session_state.enhancer_results
        
        files[0].seek(0)
        col1, col2 = st.columns(2)
        col1.image(Image.open(files[0]), caption="Original", width='stretch')
        col2.image(processed_images[0][1], caption="Processed", width='stretch')
        
        if len(processed_images) == 1:
            st.success("Your image has been processed.")
            base, path = processed_images[0]
            filename, mime, _ = get_file_meta(base, "enhanced")
            with Image.open(path) as img:
                img_data = get_download_data(img)
            st.download_button(label=f"⬇️ Download {filename}", data=img_data, file_name=filename, mime=mime, width='stretch')
        else:
            st.success(f"All {len(processed_images)} images have been processed.")
            st.info("A preview of the first image is shown above.")
            create_zip_download_button(processed_images, "enhanced_images", "enhanced")

def stats_logic(files=None):
    st.subheader("App Usage Statistics")
    st.info("Note: Because this app runs on a cloud server, these statistics will reset if the server reboots or goes to sleep.")
    
    df = get_stats()
    
    if df.empty:
        st.write("No usage data recorded yet.")
        return

    # Calculate totals
    total_uses = df['uses'].sum()
    total_images = df['images_processed'].sum()
    
    # Display high-level metrics
    col1, col2 = st.columns(2)
    col1.metric("Total Tool Executions", total_uses)
    col2.metric("Total Images Processed", total_images)
    
    st.divider()
    
    # Display the breakdown table
    st.write("**Breakdown by Tool**")
    
    # Clean up the dataframe for display
    df.columns = ['Tool Name', 'Total Uses', 'Images Processed']
    df['Tool Name'] = df['Tool Name'].str.capitalize()
    
    st.dataframe(df, width='stretch', hide_index=True)


# --- MAIN APP LAYOUT ---
st.set_page_config(page_title="altaycoins Coin Imaging Suite", layout="centered", initial_sidebar_state="expanded")

with st.sidebar:
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path)
    st.divider()
    
    st.session_state.global_format = st.selectbox(
        "Download Format", 
        options=["JPEG", "PNG"],
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
    'enhancer': enhancer_logic,
    'stats': stats_logic
}

current_view = st.session_state.get('view', 'remover')
tool_function = tool_logic_map.get(current_view)

if tool_function:
    st.title(TOOL_PAGES[current_view])
    if current_view in TOOL_INFO:
         info_box(TOOL_INFO[current_view])

    # If the user switches tools, clean up the disk and state automatically
    if 'last_view' not in st.session_state or st.session_state.last_view != current_view:
        keys_to_clear = [
            'remover_results', 'stitcher_results', 'swapper_results', 'splitter_results', 
            'remover_id', 'swapper_id', 'splitter_id', 'corrector_results', 'corrector_files_id', 
            'watermarker_results', 'watermarker_files_id', 'enhancer_results', 'enhancer_files_id'
        ]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        cleanup_temp_dir()
        
    st.session_state.last_view = current_view
    
    # Hide the file uploader if the user is on the Stats page
    if current_view != 'stats':
        uploaded_files = st.file_uploader(
            "Upload your image(s)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=current_view
        )
        if uploaded_files:
            tool_function(uploaded_files)
    else:
        tool_function()
else:
    st.session_state.view = 'remover'
    st.rerun()

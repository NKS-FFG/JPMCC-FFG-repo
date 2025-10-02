import torch
import torchvision.transforms as transforms
import torchvision.models as models
from PIL import Image
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import psycopg2
import os, platform
from collections import defaultdict
from odoo.tools import config

# ==== CONFIGURATION ====

def get_default_data_dir():
    system = platform.system()
    if system == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Odoo/")
    elif system == "Windows":
        return os.path.join(os.environ.get("APPDATA", ""), "Odoo")
    else:  # Linux and others
        return os.path.expanduser("~/.local/share/Odoo/")
    
DB_NAME = config.get('db_name') 
DB_USER = config.get('db_user')
DB_PASSWORD = ""  
DB_HOST = config.get('db_host')
DB_PORT = config.get('db_port')
DATA_DIR = get_default_data_dir()

# ==== Load Pre-trained Model ====
model = models.resnet50(pretrained=True)
model = torch.nn.Sequential(*list(model.children())[:-1])  # Remove classification head
model.eval()

# Image preprocessing
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],  # ImageNet mean
        std=[0.229, 0.224, 0.225]    # ImageNet std
    )
])

# === Utility to safely load and convert images ===
def safe_load_image(image_path):
    """
    Safely load an image and convert it to RGB format.
    Handles palette images with transparency and other edge cases.
    """
    try:
        # Check if file exists and is readable
        if not os.path.exists(image_path):
            print(f"File does not exist: {image_path}")
            return None
            
        if not os.access(image_path, os.R_OK):
            print(f"File is not readable: {image_path}")
            return None
            
        # Check file size
        file_size = os.path.getsize(image_path)
        if file_size == 0:
            print(f"File is empty: {image_path}")
            return None
            
        # Try to detect file type
        try:
            with Image.open(image_path) as img:
                img.verify()  # Verify the image is valid
        except Exception as verify_error:
            print(f"Image verification failed for {image_path}: {str(verify_error)}")
            return None
            
        # Now actually load the image
        image = Image.open(image_path)
        
        # Handle palette images with transparency
        if image.mode == 'P':
            if 'transparency' in image.info:
                # Convert palette with transparency to RGBA first
                image = image.convert('RGBA')
            else:
                # Convert palette without transparency to RGB
                image = image.convert('RGB')
        
        # Convert other formats to RGB
        elif image.mode in ('RGBA', 'LA'):
            # Create a white background for images with alpha channel
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
            else:  # LA mode
                background.paste(image.convert('RGB'))
            image = background
        
        # Ensure final image is RGB
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        return image
    
    except FileNotFoundError:
        print(f"File not found: {image_path}")
        return None
    except PermissionError:
        print(f"Permission denied: {image_path}")
        return None
    except OSError as e:
        print(f"OS error loading {image_path}: {str(e)}")
        return None
    except Exception as e:
        print(f"Unexpected error loading image {image_path}: {str(e)}")
        return None

# === Utility to extract feature vector ===
def extract_features(image_path):
    """Extract feature vector from an image."""
    try:
        image = safe_load_image(image_path)
        if image is None:
            return None
            
        image_tensor = transform(image).unsqueeze(0)  # Add batch dimension
        with torch.no_grad():
            features = model(image_tensor).squeeze().numpy()
        return features.reshape(1, -1)
    
    except Exception as e:
        print(f"Error extracting features from {image_path}: {str(e)}")
        return None

# === Batch feature extraction for multiple images ===
def extract_features_batch(image_paths, batch_size=8):
    """
    Extract features from multiple images in batches for efficiency.
    
    Args:
        image_paths: list of image paths
        batch_size: number of images to process in each batch
    
    Returns:
        dict mapping image_path to feature vector (or None if failed)
    """
    results = {}
    
    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i + batch_size]
        batch_images = []
        valid_paths = []
        
        # Load and preprocess batch
        for path in batch_paths:
            image = safe_load_image(path)
            if image is not None:
                try:
                    image_tensor = transform(image)
                    batch_images.append(image_tensor)
                    valid_paths.append(path)
                except Exception as e:
                    print(f"Error preprocessing {path}: {str(e)}")
                    results[path] = None
            else:
                results[path] = None
        
        # Process batch if we have valid images
        if batch_images:
            try:
                batch_tensor = torch.stack(batch_images)
                with torch.no_grad():
                    batch_features = model(batch_tensor).squeeze().numpy()
                
                # Handle single image case
                if len(valid_paths) == 1:
                    batch_features = batch_features.reshape(1, -1)
                
                # Store results
                for j, path in enumerate(valid_paths):
                    if len(valid_paths) == 1:
                        results[path] = batch_features
                    else:
                        results[path] = batch_features[j:j+1]
                        
            except Exception as e:
                print(f"Error processing batch: {str(e)}")
                for path in valid_paths:
                    results[path] = None
    
    return results

# === Fetch image paths stored in the database ===
def get_image_paths_from_db():
    """Fetch all image attachments from the database."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        cur.execute("""              
            SELECT
                PT.ID AS PRODUCT_ID,
                PT.NAME AS PRODUCT_NAME,
                ATTACHMENT.ID AS IMAGE_ID,
                ATTACHMENT.STORE_FNAME AS STORE_FNAME
            FROM
                IR_ATTACHMENT AS ATTACHMENT
                JOIN PRODUCT_IMAGE AS PI ON ATTACHMENT.RES_ID = PI.ID
                JOIN PRODUCT_TEMPLATE AS PT ON PI.PRODUCT_TMPL_ID = PT.ID
            WHERE
                ATTACHMENT.RES_MODEL = 'product.image'
                AND DRAFT_PRODUCT_ID IS NOT NULL
                AND ATTACHMENT.RES_FIELD = 'image_1920'
                AND PT.IS_PUBLISHED = TRUE
            ORDER BY
                PT.ID;
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for row in rows:
            if len(row) >= 4 and row[3]:  # Check if store_fname exists and is not NULL
                product_id, product_name, image_id, store_fname = row[0], row[1], row[2], row[3]
                
                result.append({
                    "path": os.path.join(DATA_DIR, 'filestore', DB_NAME, store_fname),
                    "filename": product_name.get('en_US', str(product_name)) if isinstance(product_name, dict) else str(product_name),
                    "id": image_id,
                    "product_id": product_id
                })
        return result
    
    except Exception as e:
        print(f"Database error: {str(e)}")
        return []

# === Utility to inspect problematic files ===
def inspect_file(file_path):
    """Inspect a file to understand why it might be failing."""
    print(f"\n=== Inspecting file: {file_path} ===")
    
    # Check basic file properties
    if not os.path.exists(file_path):
        print("File does not exist")
        return
    
    stat = os.stat(file_path)
    print(f"File size: {stat.st_size} bytes")
    print(f"File permissions: {oct(stat.st_mode)}")
    
    # Try to read first few bytes
    try:
        with open(file_path, 'rb') as f:
            header = f.read(20)
            print(f"File header (first 20 bytes): {header}")
            
            # Try to identify file type from header
            if header.startswith(b'\x89PNG'):
                print("Detected: PNG image")
            elif header.startswith(b'\xFF\xD8\xFF'):
                print("Detected: JPEG image")
            elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
                print("Detected: GIF image")
            elif header.startswith(b'BM'):
                print("Detected: BMP image")
            elif header.startswith(b'RIFF') and b'WEBP' in header:
                print("Detected: WebP image")
            else:
                print("Unknown file type")
    except Exception as e:
        print(f" Error reading file: {str(e)}")
    
    # Try PIL Image.open
    try:
        with Image.open(file_path) as img:
            print(f"PIL Image info:")
            print(f"Format: {img.format}")
            print(f"Mode: {img.mode}")
            print(f"Size: {img.size}")
            if hasattr(img, 'info'):
                print(f"   Info: {img.info}")
    except Exception as e:
        print(f"PIL failed to open: {str(e)}")

def find_top_matches_improved(reference_image_path, comparison_image_dicts, top_k=3):
    """Find top matching images based on feature similarity."""
    try:
        reference_features = extract_features(reference_image_path)
        if reference_features is None:
            print(f"Could not extract features from reference image: {reference_image_path}")
            return []
            
        similarities = []
        failed_files = []

        for item in comparison_image_dicts:
            path = item["path"]
            product_name = item["filename"]
            image_id = item["id"]
            product_id = item.get("product_id")
            
            if not os.path.exists(path):
                print(f"File does not exist: {path}")
                continue

            comp_features = extract_features(path)
            if comp_features is None:
                failed_files.append(path)
                continue
                
            sim = cosine_similarity(reference_features, comp_features)[0][0]
            similarities.append({
                "filename": product_name,
                "similarity": float(sim) * 100,  
                "id": image_id,
                "product_id": product_id
            })

        # Sort by similarity descending
        top_matches = sorted(similarities, key=lambda x: x["similarity"], reverse=True)[:top_k]
        
        print(f"\nFound {len(top_matches)} matches out of {len(comparison_image_dicts)} total files")
        if failed_files:
            print(f"Failed to process {len(failed_files)} files")
        
        # Inspect first few failed files for debugging
        if failed_files and len(failed_files) <= 3:
            print("\n=== Inspecting failed files ===")
            for failed_file in failed_files[:3]:  # Only inspect first 3 failed files
                inspect_file(failed_file)
        
        for match in top_matches:
            print(f"Match: {match['filename']}, Similarity: {match['similarity']:.4f}, ID: {match['id']}")
            
        return top_matches
    
    except Exception as e:
        print(f"Error in find_top_matches: {str(e)}")
        return []

# === Enhanced matching for multiple images with batch processing ===
def find_matches_batch_optimized(reference_image_paths, comparison_image_dicts, top_k_per_image=20):
    """
    Find matches for multiple reference images using batch processing for efficiency.
    
    Args:
        reference_image_paths: list of reference image paths
        comparison_image_dicts: list of comparison image dictionaries
        top_k_per_image: top matches to consider per reference image
    
    Returns:
        dict mapping reference_image_path to list of matches
    """
    try:
        # Extract features for all reference images
        print(f"Extracting features for {len(reference_image_paths)} reference images...")
        reference_features_map = extract_features_batch(reference_image_paths)
        
        # Filter out failed reference images
        valid_references = [(path, features) for path, features in reference_features_map.items() 
                          if features is not None]
        
        if not valid_references:
            print("No valid reference images found")
            return {}
        
        print(f"Successfully extracted features for {len(valid_references)} reference images")
        
        # Extract features for comparison images (with caching for efficiency)
        comparison_paths = [item["path"] for item in comparison_image_dicts if os.path.exists(item["path"])]
        print(f"Extracting features for {len(comparison_paths)} comparison images...")
        comparison_features_map = extract_features_batch(comparison_paths, batch_size=16)
        
        # Build valid comparison data
        valid_comparisons = []
        for item in comparison_image_dicts:
            path = item["path"]
            if path in comparison_features_map and comparison_features_map[path] is not None:
                valid_comparisons.append({
                    **item,
                    "features": comparison_features_map[path]
                })
        
        print(f"Successfully extracted features for {len(valid_comparisons)} comparison images")
        
        # Find matches for each reference image
        all_matches = {}
        
        for ref_path, ref_features in valid_references:
            print(f"Finding matches for: {os.path.basename(ref_path)}")
            similarities = []
            
            for comp_item in valid_comparisons:
                try:
                    sim = cosine_similarity(ref_features, comp_item["features"])[0][0]
                    similarities.append({
                        "filename": comp_item["filename"],
                        "similarity": float(sim) * 100,
                        "id": comp_item["id"],
                        "product_id": comp_item.get("product_id"),
                        "path": comp_item["path"]
                    })
                except Exception as e:
                    print(f"Error calculating similarity: {str(e)}")
                    continue
            
            # Sort and get top matches
            top_matches = sorted(similarities, key=lambda x: x["similarity"], reverse=True)[:top_k_per_image]
            all_matches[ref_path] = top_matches
            
            print(f"Found {len(top_matches)} matches for {os.path.basename(ref_path)}")
        
        return all_matches
    
    except Exception as e:
        print(f"Error in find_matches_batch_optimized: {str(e)}")
        return {}
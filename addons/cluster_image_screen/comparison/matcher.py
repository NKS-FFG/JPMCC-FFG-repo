import torch
import torchvision.transforms as transforms
import torchvision.models as models
from PIL import Image
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import psycopg2
import os
import warnings
from collections import defaultdict

# ==== CONFIGURATION ====
DB_NAME = "aniruddhadhawad"  # replace with your actual DB name
DB_USER = "aniruddhadhawad"
DB_PASSWORD = ""  # add password if required
DB_HOST = "localhost"
DB_PORT = "5432"
DATA_DIR = "/Users/aniruddhadhawad/Library/Application Support/Odoo/"

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
            DISTINCT ON (pt.id)
            pt.id as product_id,
            pt.name as product_name,
            ia.id as image_id,
            ia.store_fname as store_fname
            FROM
            PRODUCT_TEMPLATE pt
            LEFT JOIN IR_ATTACHMENT IA ON IA.RES_MODEL = 'product.template'
            AND ia.res_id = pt.id
            AND ia.mimetype LIKE 'image/%'
            WHERE pt.active = true AND pt.is_published = true
            ORDER BY pt.id, ia.res_field;
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

# === Main matching logic (original, for backward compatibility) ===
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
                "similarity": float(sim) * 100,  # Convert to percentage
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

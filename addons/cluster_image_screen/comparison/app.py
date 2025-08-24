from .matcher import get_image_paths_from_db, find_top_matches_improved
import os
from collections import defaultdict
import tempfile

def calculate_combined_score(product_matches, total_images, frequency_weight=0.4, similarity_weight=0.6):
    """
    Calculate combined score based on frequency and average similarity
    
    Args:
        product_matches: dict with product info and list of similarity scores
        total_images: total number of uploaded images
        frequency_weight: weight for frequency component (0-1)
        similarity_weight: weight for similarity component (0-1)
    
    Returns:
        dict with combined score and component scores
    """
    appearances = len(product_matches['similarities'])
    frequency_score = (appearances / total_images) * 100
    avg_similarity = sum(product_matches['similarities']) / len(product_matches['similarities'])
    
    combined_score = (frequency_score * frequency_weight) + (avg_similarity * similarity_weight)
    
    return {
        'combined_score': combined_score,
        'frequency_score': frequency_score,
        'avg_similarity': avg_similarity,
        'appearances': appearances,
        'total_images': total_images
    }

def find_best_matches_multiple_images(uploaded_images_paths, comparison_paths, top_k=5, frequency_weight=0.4, similarity_weight=0.6):
    """
    Find best matching products across multiple uploaded images using hybrid scoring
    
    Args:
        uploaded_images_paths: list of paths to uploaded images
        comparison_paths: list of comparison image dictionaries from database
        top_k: number of top matches to return
        frequency_weight: weight for frequency component
        similarity_weight: weight for similarity component
    
    Returns:
        list of top matching products with combined scores
    """
    # Dictionary to store all matches for each product
    product_matches = defaultdict(lambda: {
        'filename': None,
        'id': None,
        'product_id': None,
        'similarities': [],
        'max_similarity': 0,
        'min_similarity': 100
    })
    
    total_images = len(uploaded_images_paths)
    
    print(f"Processing {total_images} uploaded images against {len(comparison_paths)} database images")
    
    # Process each uploaded image
    for idx, uploaded_path in enumerate(uploaded_images_paths):
        print(f"Processing uploaded image {idx + 1}/{total_images}: {uploaded_path}")
        
        # Get top matches for this single image
        single_image_matches = find_top_matches_improved(uploaded_path, comparison_paths, top_k=20)
        
        # Process matches for this image
        for match in single_image_matches:
            product_key = f"{match['id']}_{match.get('product_id', 'unknown')}"
            
            # Initialize product info if first time seeing this product
            if product_matches[product_key]['filename'] is None:
                product_matches[product_key]['filename'] = match['filename']
                product_matches[product_key]['id'] = match['id']
                product_matches[product_key]['product_id'] = match.get('product_id')
            
            # Add similarity score
            similarity = match['similarity']
            product_matches[product_key]['similarities'].append(similarity)
            product_matches[product_key]['max_similarity'] = max(
                product_matches[product_key]['max_similarity'], similarity
            )
            product_matches[product_key]['min_similarity'] = min(
                product_matches[product_key]['min_similarity'], similarity
            )
    
    # Calculate combined scores for all products
    final_results = []
    for product_key, match_data in product_matches.items():
        if not match_data['similarities']:  # Skip if no matches
            continue
            
        scores = calculate_combined_score(match_data, total_images, frequency_weight, similarity_weight)
        
        final_results.append({
            'filename': match_data['filename'],
            'id': match_data['id'],
            'product_id': match_data['product_id'],
            'combined_score': scores['combined_score'],
            'frequency_score': scores['frequency_score'],
            'avg_similarity': scores['avg_similarity'],
            'max_similarity': match_data['max_similarity'],
            'min_similarity': match_data['min_similarity'],
            'appearances': scores['appearances'],
            'total_uploaded_images': total_images,
            'individual_similarities': match_data['similarities']
        })
    
    # Sort by combined score descending
    final_results.sort(key=lambda x: x['combined_score'], reverse=True)
    
    return final_results[:top_k]

def compare_multiple_images(uploaded_files, top_k=3, frequency_weight=0.4, similarity_weight=0.6):
    """Handle multiple image comparison with hybrid scoring"""

    
    if not uploaded_files or len(uploaded_files) == 0:
        return {'error': 'No images provided'}
    
    print(f"Received {len(uploaded_files)} images for comparison")
    
    # Validate weights
    if abs((frequency_weight + similarity_weight) - 1.0) > 0.001:
        return {'error': 'Frequency and similarity weights must sum to 1.0'}
    
    uploaded_paths = []
    temp_files = []
    
    try:
        # Save all uploaded images to temporary files
        for idx, uploaded_file in enumerate(uploaded_files):
            if uploaded_file.filename == '':
                continue
                
            print(f"Processing upload {idx + 1}: {uploaded_file.filename}")
            
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            uploaded_path = temp_file.name
            temp_file.close()
            
            uploaded_file.save(uploaded_path)
            uploaded_paths.append(uploaded_path)
            temp_files.append(uploaded_path)
        
        if not uploaded_paths:
            return {'error': 'No valid images to process'}
        
        # Get comparison images from database
        comparison_paths = get_image_paths_from_db()
        
        if not comparison_paths:
            return {'error': 'No images found in database for comparison.'}
        
        # Find best matches using hybrid approach
        top_matches = find_best_matches_multiple_images(
            uploaded_paths, 
            comparison_paths, 
            top_k=top_k,
            frequency_weight=frequency_weight,
            similarity_weight=similarity_weight
        )
        
        response_data = {
            'top_matches': top_matches,
            'total_uploaded_images': len(uploaded_paths),
            'total_database_images': len(comparison_paths),
            'scoring_parameters': {
                'frequency_weight': frequency_weight,
                'similarity_weight': similarity_weight,
                'top_k': top_k
            }
        }

        print("response data: ", response_data)
        
        return response_data
    
    except Exception as e:
        print(f"Error in multiple image comparison: {str(e)}")
        return {'error': str(e)}
    
    finally:
        # Clean up all temporary files
        for temp_path in temp_files:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print(f"Failed to remove temp file {temp_path}: {str(e)}")

if __name__ == '__main__':
    # Ensure temp directory exists
    os.makedirs("temp", exist_ok=True)
    #app.run(host='0.0.0.0', port=5001, debug=True)
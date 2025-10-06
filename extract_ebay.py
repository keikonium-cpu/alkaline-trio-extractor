import requests
from io import BytesIO
from PIL import Image
import pytesseract
import json
import re
import os
from datetime import datetime

def fetch_image_urls(base_url):
    """Fetch the HTML and extract image URLs with unique IDs."""
    try:
        response = requests.get(base_url)
        response.raise_for_status()
        html = response.text
        
        # Use BeautifulSoup for robust parsing
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        # Adjust this selector based on your HTML (e.g., img tags with data-id)
        # Example: assumes <img src="..." data-id="123">; tweak if needed
        image_urls = {}
        for img in soup.find_all('img', attrs={'data-id': True}):
            img_id = img.get('data-id')
            src = img.get('src')
            if img_id and src:
                # Ensure full URL if relative
                if not src.startswith('http'):
                    src = base_url.rstrip('/') + '/' + src.lstrip('/')
                image_urls[img_id] = src
        print(f"Found {len(image_urls)} image URLs: {list(image_urls.keys())}")  # Debug log
        return image_urls
    except Exception as e:
        print(f"Error fetching image URLs: {e}")
        return {}

def extract_ebay_listings(image_url):
    """Perform OCR on an image URL and return parsed listing data."""
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        listings = []
        current = {}
        seller_regex = re.compile(r'^\w+\s*(?:\d{1,3}%?)?\s*\(\d+(?:\.\d+)?[KkMm]?\)$')
        
        for line in lines:
            if line.startswith('Sold'):
                if current.get('sold_date'):
                    listings.append(current)
                current = {'sold_date': line}
            elif line.startswith('$'):
                current['sold_price'] = line
            elif seller_regex.match(line) or 'positive' in line.lower():
                current['seller'] = line
            else:
                if 'listing_title' in current:
                    current['listing_title'] += ' ' + line
                else:
                    current['listing_title'] = line
        
        if current.get('sold_date'):
            listings.append(current)
        
        print(f"Extracted {len(listings)} listings from {image_url}")  # Debug log
        return listings
    except Exception as e:
        print(f"Error processing {image_url}: {e}")
        return []

def update_listings():
    """Main function: Fetch new images, process, and update JSON."""
    base_url = 'http://www.alkalinetrioarchive.com/screenshots.html'
    output_json = 'listings.json'
    
    # Load existing listings from repo file
    existing_ids = set()
    all_listings = []
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('image_id', '') for item in data}
    
    # Fetch new image URLs
    image_urls = fetch_image_urls(base_url)
    new_listings = []
    
    for img_id, img_url in image_urls.items():
        if img_id not in existing_ids:
            print(f"Processing new image ID: {img_id} from {img_url}")
            listings = extract_ebay_listings(img_url)
            for listing in listings:
                listing['image_id'] = img_id
                listing['processed_at'] = datetime.now().isoformat()  # Timestamp for tracking
                new_listings.append(listing)
            existing_ids.add(img_id)
    
    # Always save (append new + existing), even if no new
    if new_listings:
        all_listings.extend(new_listings)
        print(f"Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("No new listings to add. Saving existing data.")
    
    # Ensure JSON always exists (write empty list if first run)
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=4)
    
    return len(new_listings) > 0  # True if changes made

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("Run committed changes to repo.")  # Handled by workflow
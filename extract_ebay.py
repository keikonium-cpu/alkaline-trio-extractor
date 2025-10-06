import json
import re
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

def fetch_image_urls(base_url):
    """Fetch the rendered HTML with Selenium and extract image URLs with unique IDs."""
    try:
        # Set up headless Chrome
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=chrome_options)
        
        print(f"Loading page with Selenium: {base_url}")
        driver.get(base_url)
        
        # Wait for at least one gallery item to load (up to 30s)
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
        print("First gallery-item detected—JS loaded successfully!")
        
        # Now get ALL gallery items
        gallery_divs = driver.find_elements(By.CSS_SELECTOR, ".gallery-item")
        print(f"Found {len(gallery_divs)} gallery-item divs after JS load")  # Debug: Now safe len()
        
        # Get full rendered HTML
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Select .gallery-item divs, get data-id, and src from inner img
        gallery_elements = soup.find_all('div', class_='gallery-item')
        print(f"Parsed {len(gallery_elements)} gallery-item divs in HTML")  # Debug
        
        if len(gallery_elements) == 0:
            print("No gallery-item divs found in rendered HTML. Snippet (first 1000 chars):")
            print(html[:1000])  # Debug: Show rendered HTML
            driver.quit()
            return {}
        
        image_urls = {}
        for gallery in gallery_elements:
            img_id = gallery.get('data-id')
            img_tag = gallery.find('img')
            src = img_tag.get('src') if img_tag else None
            if img_id and src:
                image_urls[img_id] = src
        print(f"Found {len(image_urls)} image URLs: {list(image_urls.keys())}")  # Debug log
        driver.quit()
        return image_urls
    except Exception as e:
        print(f"Error fetching image URLs with Selenium: {e}")
        # On error, try to get page source for debug
        try:
            driver.quit()
        except:
            pass
        return {}

def extract_ebay_listings(image_url):
    """Perform OCR on an image URL and return parsed listing data."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip() and len(line) > 2]  # Basic filter: non-empty, >2 chars
        print(f"OCR extracted {len(lines)} raw lines (first 5): {lines[:5]}")  # Debug: Sample raw
        
        # Ignore common junk lines
        junk_patterns = [
            re.compile(r'^(Free|Located|View|eBay|Buy|Ships)$', re.I),  # Headers/shipping
            re.compile(r'^\d+%?\s*\(\d+[KkMm]?\)$'),  # Pure ratings like "99% (30K)"
            re.compile(r'^\d{1,3}$'),  # Standalone numbers
        ]
        filtered_lines = [line for line in lines if not any(pat.match(line) for pat in junk_patterns)]
        print(f"Filtered to {len(filtered_lines)} clean lines (first 3): {filtered_lines[:3]}")  # Debug
        
        listings = []
        current = {'listing_title': ''}  # Start with empty title
        in_listing = False
        
        for line in filtered_lines:
            if line.startswith('Sold') and re.match(r'Sold\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', line):
                # New listing: Save previous if valid
                if in_listing and current.get('sold_date') and current['listing_title'].strip() and current.get('sold_price'):
                    listings.append(current)
                current = {'sold_date': line, 'listing_title': ''}
                in_listing = True
                continue
            
            if in_listing:
                if line.startswith('$') and re.match(r'^\$[\d,]+\.?\d{0,2}$', line):  # e.g., "$8.20" or "$12,345"
                    current['sold_price'] = line
                    continue  # Title is done; next "Sold" starts new
                
                # Title: Must contain "alkaline" (black text pattern), append if multi-line
                if 'alkaline' in line.lower() and not re.match(r'^\$[\d,]+\.?\d{0,2}$', line):
                    current['listing_title'] += (' ' if current['listing_title'] else '') + line
                    continue
                
                # Ignore other lines (e.g., sellers like "username 99% (257K)")
                if re.match(r'^\w+\s+\d+%?\s*\(\d+[KkMm]?\)$', line):
                    continue  # Skip sellers
        
        # Add final listing if valid
        if in_listing and current.get('sold_date') and current['listing_title'].strip() and current.get('sold_price'):
            listings.append(current)
        
        print(f"Extracted {len(listings)} clean listings from {image_url}. Sample: {listings[0] if listings else 'None'}")  # Debug
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
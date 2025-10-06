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
        
        # Wait for gallery items to load (up to 30s)
        wait = WebDriverWait(driver, 30)
        gallery_divs = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
        print(f"Found {len(gallery_divs)} gallery-item divs after JS load")  # Debug
        
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
        return {}

def extract_ebay_listings(image_url):
    """Perform OCR on an image URL and return parsed listing data."""
    try:
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        print(f"OCR extracted {len(lines)} lines (first 5): {lines[:5]}")  # Debug: Sample lines
        
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
    import requests  # Import here to avoid Selenium dependency
    updated = update_listings()
    if updated:
        print("Run committed changes to repo.")  # Handled by workflow
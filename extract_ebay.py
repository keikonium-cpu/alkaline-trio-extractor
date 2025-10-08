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
import time

def fetch_all_image_urls(base_url):
    """Fetch image URLs from ALL pages of the gallery."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=chrome_options)
        
        all_image_urls = {}
        page = 1
        
        while True:
            url = f"{base_url}?page={page}"
            print(f"Loading page {page}: {url}")
            driver.get(url)
            
            try:
                wait = WebDriverWait(driver, 30)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
                time.sleep(2)
                
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                gallery_elements = soup.find_all('div', class_='gallery-item')
                
                if len(gallery_elements) == 0:
                    print(f"No gallery items found on page {page}. Stopping.")
                    break
                
                page_images = {}
                for gallery in gallery_elements:
                    img_id = gallery.get('data-id')
                    img_tag = gallery.find('img')
                    src = img_tag.get('src') if img_tag else None
                    if img_id and src:
                        page_images[img_id] = src
                
                print(f"Page {page}: Found {len(page_images)} images")
                all_image_urls.update(page_images)
                
                pagination = soup.find('div', id='pagination')
                if pagination:
                    next_page_link = pagination.find('a', {'data-page': str(page + 1)})
                    if not next_page_link:
                        break
                else:
                    break
                
                page += 1
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                break
        
        driver.quit()
        print(f"Total images collected: {len(all_image_urls)}")
        return all_image_urls
        
    except Exception as e:
        print(f"Error fetching image URLs: {e}")
        try:
            driver.quit()
        except:
            pass
        return {}

def extract_ebay_listings(image_url):
    """Extract eBay listings with image cropping and preprocessing."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image, ImageEnhance, ImageFilter
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Crop to relevant area (remove sidebar and header)
        width, height = img.size
        img = img.crop((500, 330, width, height))
        
        # Preprocessing
        img = img.convert('L')
        img = ImageEnhance.Contrast(img).enhance(2.5)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        
        text = pytesseract.image_to_string(img, config='--oem 3 --psm 6')
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"  OCR extracted {len(lines)} lines")
        
        listings = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Find date
            date_match = re.match(r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}', line, re.I)
            if not date_match:
                i += 1
                continue
            
            listing = {
                'status': date_match.group(1).capitalize(),
                'date': line,
                'listing_title': '',
                'sold_price': None,
                'seller': None
            }
            
            print(f"    [{listing['status']}] {line}")
            i += 1
            
            # Extract title
            title_parts = []
            while i < len(lines) and len(title_parts) < 5:
                current = lines[i]
                
                # Stop conditions
                if re.match(r'^(Brand New|Pre-Owned|New with|Open box|Used|For parts|Not Specified)$', current, re.I):
                    i += 1
                    break
                if re.match(r'^\$\d+', current):
                    break
                if re.match(r'^\d+\s*(bid|watcher)', current, re.I):
                    i += 1
                    continue
                if re.match(r'^(or Best|Buy It Now|Located|View similar|Sell one|Free|Watch|\+\$)', current, re.I):
                    i += 1
                    continue
                
                # Valid title
                if len(current) > 2 and re.search(r'[a-zA-Z]{3,}', current):
                    current = re.sub(r'\bLied\b', 'I Lied', current)
                    current = re.sub(r'\bOtt\b', 'Off', current)
                    current = re.sub(r'\|', 'I', current)
                    title_parts.append(current)
                    print(f"      Title: {current}")
                
                i += 1
            
            listing['listing_title'] = ' '.join(title_parts).strip()
            
            # Extract price
            for _ in range(5):
                if i >= len(lines):
                    break
                current = lines[i]
                price_match = re.match(r'^\$(\d+[\d,]*\.?\d{0,2})$', current)
                if price_match:
                    listing['sold_price'] = f"${price_match.group(1)}"
                    print(f"      Price: {listing['sold_price']}")
                    i += 1
                    break
                i += 1
            
            # Extract seller
            for _ in range(6):
                if i >= len(lines):
                    break
                current = lines[i]
                
                if re.match(r'^(Sold|Ended)\s+', current, re.I):
                    break
                
                seller_match = re.search(r'^([a-zA-Z0-9_-]+)\s+\d+\.?\d*%', current, re.I)
                if seller_match:
                    listing['seller'] = seller_match.group(1)
                    print(f"      Seller: {listing['seller']}")
                    i += 1
                    break
                
                if re.match(r'^[a-zA-Z0-9_-]+$', current) and i + 1 < len(lines):
                    if re.search(r'\d+\.?\d*%', lines[i + 1]):
                        listing['seller'] = current
                        print(f"      Seller: {listing['seller']}")
                        i += 2
                        break
                
                i += 1
            
            # Save if valid
            if listing['listing_title'] and listing['sold_price']:
                listing['listing_title'] = re.sub(r'\s{2,}', ' ', listing['listing_title']).strip()
                listings.append(listing)
                print(f"    ✓ Saved")
            else:
                print(f"    ✗ Skipped - missing title or price")
        
        print(f"  ✓ Extracted {len(listings)} listings")
        return listings
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def update_listings():
    """Main function."""
    base_url = 'http://www.alkalinetrioarchive.com/screenshots.html'
    output_json = 'listings.json'
    
    existing_ids = set()
    all_listings = []
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('image_id', '') for item in data}
    
    print(f"Loaded {len(all_listings)} existing listings\n")
    
    image_urls = fetch_all_image_urls(base_url)
    print(f"\nFound {len(image_urls)} images\n")
    
    new_listings = []
    processed = 0
    skipped = 0
    
    for img_id, img_url in image_urls.items():
        if img_id not in existing_ids:
            processed += 1
            print(f"[{processed}] Processing: {img_id}")
            listings = extract_ebay_listings(img_url)
            for listing in listings:
                listing['image_id'] = img_id
                listing['processed_at'] = datetime.now().isoformat()
                new_listings.append(listing)
            existing_ids.add(img_id)
        else:
            skipped += 1
            if skipped % 10 == 0:
                print(f"[Skipped {skipped} images...]")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("\n✓ No new listings")
    
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=4)
    
    print(f"✓ Saved to {output_json}")
    return len(new_listings) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Changes ready for commit")
    else:
        print("\n✓ No changes to commit")
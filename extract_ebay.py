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
                        print(f"No next page link found. Stopping at page {page}.")
                        break
                else:
                    print("No pagination found. Single page gallery.")
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
    """Extract eBay sold listings following the specific pattern: Sold date → Title → Price."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Extract text with line-by-line data
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"  OCR extracted {len(lines)} raw lines")
        
        listings = []
        current = None
        state = 'looking_for_sold'  # State machine: looking_for_sold → building_title → looking_for_price
        
        for i, line in enumerate(lines):
            # STATE 1: Looking for "Sold" date (green text, small)
            if state == 'looking_for_sold':
                # Must start with "Sold" and have month/day/year
                sold_match = re.match(r'^Sold\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}', line, re.I)
                if sold_match:
                    # Save previous listing if complete
                    if current and current.get('sold_date') and current.get('listing_title') and current.get('sold_price'):
                        listings.append(current)
                    
                    # Start new listing
                    current = {
                        'sold_date': line,
                        'listing_title': '',
                        'sold_price': None,
                        'seller': None
                    }
                    state = 'building_title'
                    print(f"    Found sold date: {line}")
                continue
            
            # STATE 2: Building title (large black text, contains "alkaline")
            elif state == 'building_title':
                # Skip non-title lines
                if re.match(r'^(Brand New|Pre-Owned)$', line, re.I):
                    state = 'looking_for_price'
                    continue
                
                # Price found - stop title building
                if re.match(r'^\$[\d,]+\.?\d{0,2}$', line):
                    current['sold_price'] = line
                    state = 'looking_for_sold'
                    print(f"    Price: {line}")
                    continue
                
                # Title line detection
                # Must contain "alkaline" OR be a continuation of existing title
                has_alkaline = 'alkaline' in line.lower()
                is_continuation = (
                    current['listing_title'] and  # Already have title start
                    not line.startswith('$') and
                    not re.match(r'^Sold\s+', line, re.I) and
                    not re.match(r'^Ended\s+', line, re.I) and
                    not re.match(r'^\d+%', line) and  # Skip ratings
                    not re.match(r'^(Located|Free|Buy It Now|or Best|Shipping)', line, re.I)
                )
                
                if has_alkaline or is_continuation:
                    # Add to title
                    if current['listing_title']:
                        current['listing_title'] += ' ' + line
                    else:
                        current['listing_title'] = line
                    print(f"    Title fragment: {line}")
                continue
            
            # STATE 3: Looking for price (large green text with $)
            elif state == 'looking_for_price':
                price_match = re.match(r'^\$[\d,]+\.?\d{0,2}$', line)
                if price_match:
                    current['sold_price'] = line
                    state = 'looking_for_sold'
                    print(f"    Price: {line}")
                continue
        
        # Don't forget the last listing
        if current and current.get('sold_date') and current.get('listing_title') and current.get('sold_price'):
            listings.append(current)
        
        # Clean up titles
        for listing in listings:
            title = listing['listing_title']
            # Remove trailing junk patterns
            title = re.sub(r'\s+(Related:|Include description|View similar|Sell one like|Extra \d+%|or Best Offer).*$', '', title, flags=re.I)
            # Remove "Direct from eBay" and similar
            title = re.sub(r'\s+Direct from eBay.*$', '', title, flags=re.I)
            # Trim whitespace
            listing['listing_title'] = title.strip()
        
        print(f"  ✓ Extracted {len(listings)} valid SOLD listings")
        for idx, listing in enumerate(listings, 1):
            print(f"    [{idx}] {listing['sold_date']} - {listing['listing_title'][:50]}... - {listing['sold_price']}")
        
        return listings
        
    except Exception as e:
        print(f"  ✗ Error processing {image_url}: {e}")
        import traceback
        traceback.print_exc()
        return []

def update_listings():
    """Main function: Fetch all pages, process new images, update JSON."""
    base_url = 'http://www.alkalinetrioarchive.com/screenshots.html'
    output_json = 'listings.json'
    
    # Load existing listings
    existing_ids = set()
    all_listings = []
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('image_id', '') for item in data}
    
    print(f"Loaded {len(all_listings)} existing listings with {len(existing_ids)} unique image IDs\n")
    
    # Fetch ALL image URLs from all pages
    image_urls = fetch_all_image_urls(base_url)
    print(f"\nFound {len(image_urls)} total images across all pages\n")
    
    new_listings = []
    processed_count = 0
    skipped_count = 0
    
    for img_id, img_url in image_urls.items():
        if img_id not in existing_ids:
            processed_count += 1
            print(f"[{processed_count}] Processing NEW: {img_id}")
            listings = extract_ebay_listings(img_url)
            for listing in listings:
                listing['image_id'] = img_id
                listing['processed_at'] = datetime.now().isoformat()
                new_listings.append(listing)
            existing_ids.add(img_id)
        else:
            skipped_count += 1
            print(f"[Skip {skipped_count}] Already processed: {img_id}")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("\n✓ No new listings to add.")
    
    # Save JSON
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=4)
    
    return len(new_listings) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Changes ready for commit")
    else:
        print("\n✓ No changes to commit")
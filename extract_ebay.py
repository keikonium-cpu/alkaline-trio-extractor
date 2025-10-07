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
                # Wait for gallery items to load
                wait = WebDriverWait(driver, 30)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
                time.sleep(2)  # Extra wait for dynamic content
                
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
                
                # Check if there's a next page link
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
    """Perform OCR with improved text filtering."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # OCR with better configuration
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(img, config=custom_config)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"OCR extracted {len(lines)} lines")
        
        # Aggressive filtering for junk
        junk_patterns = [
            re.compile(r'^(Free|Located|View|eBay|Buy|Ships|Shipping|Watching|Watchers|Seller|Top Rated).*', re.I),
            re.compile(r'^\d+%?\s*\(\d+[KkMm]?\)$'),  # Ratings
            re.compile(r'^\d{1,3}$'),  # Standalone numbers
            re.compile(r'^(Brand New|Pre-Owned|New|Used|Condition).*', re.I),
            re.compile(r'^(Related:|Include description|Local Pickup|Item Location).*', re.I),
            re.compile(r'^\([0-9]+\)$'),  # (75), etc.
            re.compile(r'^[A-Z]{2}$'),  # State codes like "CO"
            re.compile(r'^Not Specified.*', re.I),
            re.compile(r'^(nofx|rancid|bad religion)(?!.*alkaline)', re.I),  # Other bands unless with "alkaline"
        ]
        
        filtered_lines = []
        for line in lines:
            is_junk = any(pat.match(line) for pat in junk_patterns)
            if not is_junk:
                filtered_lines.append(line)
        
        print(f"Filtered to {len(filtered_lines)} clean lines")
        
        listings = []
        current = None
        
        for i, line in enumerate(filtered_lines):
            # Detect new listing by "Sold" date
            sold_match = re.match(r'Sold\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', line)
            
            if sold_match:
                # Save previous listing if valid
                if current and current.get('sold_date') and current.get('listing_title', '').strip() and current.get('sold_price'):
                    # Clean up title
                    title = current['listing_title'].strip()
                    # Remove trailing junk patterns
                    title = re.sub(r'\s*(Related:|Include description|nofx|rancid).*$', '', title, flags=re.I)
                    current['listing_title'] = title
                    listings.append(current)
                
                # Start new listing
                current = {
                    'sold_date': line,
                    'listing_title': '',
                    'sold_price': None,
                    'seller': None
                }
                continue
            
            if current is None:
                continue  # Haven't found first listing yet
            
            # Price detection (must be standalone)
            price_match = re.match(r'^\$[\d,]+\.?\d{0,2}$', line)
            if price_match and not current.get('sold_price'):
                current['sold_price'] = line
                continue
            
            # Title detection: Must contain "alkaline" (case insensitive)
            if 'alkaline' in line.lower():
                # Don't add if it's a price or already has price
                if not re.match(r'^\$', line):
                    if current['listing_title']:
                        current['listing_title'] += ' ' + line
                    else:
                        current['listing_title'] = line
                continue
            
            # Seller detection (username + rating pattern)
            seller_match = re.match(r'^(\w+)\s+\d+%?\s*\(\d+[KkMm]?\)$', line)
            if seller_match and not current.get('seller'):
                current['seller'] = seller_match.group(1)
                continue
        
        # Add final listing
        if current and current.get('sold_date') and current.get('listing_title', '').strip() and current.get('sold_price'):
            title = current['listing_title'].strip()
            title = re.sub(r'\s*(Related:|Include description|nofx|rancid).*$', '', title, flags=re.I)
            current['listing_title'] = title
            listings.append(current)
        
        print(f"Extracted {len(listings)} valid listings")
        return listings
        
    except Exception as e:
        print(f"Error processing {image_url}: {e}")
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
    
    print(f"Loaded {len(all_listings)} existing listings with {len(existing_ids)} unique image IDs")
    
    # Fetch ALL image URLs from all pages
    image_urls = fetch_all_image_urls(base_url)
    print(f"Found {len(image_urls)} total images across all pages")
    
    new_listings = []
    
    for img_id, img_url in image_urls.items():
        if img_id not in existing_ids:
            print(f"\n--- Processing NEW image: {img_id} ---")
            listings = extract_ebay_listings(img_url)
            for listing in listings:
                listing['image_id'] = img_id
                listing['processed_at'] = datetime.now().isoformat()
                new_listings.append(listing)
            existing_ids.add(img_id)
        else:
            print(f"Skipping existing image: {img_id}")
    
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
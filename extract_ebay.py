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
    """Extract eBay listings with image preprocessing and improved pattern matching."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image, ImageEnhance, ImageFilter
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # IMAGE PREPROCESSING
        img = img.convert('L')
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.5)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(img, config=custom_config)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"  OCR extracted {len(lines)} raw lines")
        
        listings = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            date_match = re.match(
                r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
                line,
                re.I
            )
            
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
            
            # EXTRACT TITLE
            title_lines = []
            max_title_search = 15
            title_start_idx = i
            
            while i < len(lines) and (i - title_start_idx) < max_title_search:
                current = lines[i]
                
                price_pattern = r'^\$\d+[\d,]*\.?\d{0,2}$'
                if re.match(price_pattern, current):
                    print(f"      Found price, stopping title: {current}")
                    break
                
                if re.match(r'^(Brand New|Pre-Owned|New with tags|New without tags|Open box|Used|For parts)$', current, re.I):
                    print(f"      Condition found: {current}")
                    i += 1
                    break
                
                if re.search(r'\d+\.?\d*%\s*positive', current, re.I):
                    print(f"      Seller pattern found: {current}")
                    break
                
                skip_patterns = [
                    r'^(Buy It Now|or Best Offer|Make Offer|Auction|Bids?:)',
                    r'^(Located in|Shipping|Delivery|Returns)',
                    r'^(Authenticity Guarantee|Top Rated|Trending)',
                    r'^\d+\s*(bid|watcher)',
                    r'^(Free|Watch|Save)',
                    r'^(More \+|Extra \d+%)',
                    r'^(Item Location|Default|Within)',
                    r'^\$\d+\.\d{2}\s+to\s+\$',
                    r'^Available inventory',
                    r'^Scratch Free',
                    r'product rating',
                    r'^\{.*\}',
                    r'^@\s*\w+',
                    r'^O\s+Within',
                ]
                
                should_skip = False
                for pattern in skip_patterns:
                    if re.search(pattern, current, re.I):
                        should_skip = True
                        break
                
                if should_skip:
                    i += 1
                    continue
                
                embedded_price = re.search(r'\$\d+[\d,]*\.?\d{0,2}$', current)
                if embedded_price:
                    title_part = current[:embedded_price.start()].strip()
                    if title_part and len(title_part) > 3:
                        title_lines.append(title_part)
                        print(f"      Title (with embedded price): {title_part}")
                    print(f"      Found embedded price: {embedded_price.group()}")
                    i += 1
                    break
                
                if len(current) > 2:
                    title_lines.append(current)
                    print(f"      Title: {current}")
                
                i += 1
            
            listing['listing_title'] = ' '.join(title_lines).strip()
            
            # EXTRACT PRICE
            price_search_start = i
            max_price_search = 10
            
            while i < len(lines) and (i - price_search_start) < max_price_search:
                current = lines[i]
                
                price_match = re.search(r'\$(\d+[\d,]*\.?\d{0,2})', current)
                if price_match:
                    listing['sold_price'] = f"${price_match.group(1)}"
                    print(f"      Price: {listing['sold_price']}")
                    i += 1
                    break
                
                i += 1
            
            # EXTRACT SELLER
            seller_search_start = i
            while i < len(lines) and i < seller_search_start + 8:
                current = lines[i]
                
                if re.match(r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', current, re.I):
                    break
                
                seller_match = re.search(
                    r'^(.+?)\s*(\d+\.?\d*)%\s*(?:positive|feedback)',
                    current,
                    re.I
                )
                
                if seller_match:
                    seller_name = seller_match.group(1).strip()
                    seller_name = re.sub(r'^(by|from|seller:?|ts)\s+', '', seller_name, flags=re.I)
                    seller_name = re.sub(r'\s+\d+$', '', seller_name)
                    if len(seller_name) > 2:
                        listing['seller'] = seller_name
                        print(f"      Seller: {listing['seller']}")
                    i += 1
                    break
                
                current_clean = re.sub(r'^(by|from|seller:?|ts)\s+', '', current, flags=re.I)
                if (not re.match(r'^\$', current) and 
                    len(current_clean) > 2 and
                    not re.match(r'^(Located|Shipping|Buy|or Best|Free|Watch|Bid)', current, re.I)):
                    
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if re.search(r'\d+\.?\d*%\s*(?:positive|feedback)', next_line, re.I):
                            listing['seller'] = current_clean.strip()
                            print(f"      Seller (split): {listing['seller']}")
                            i += 2
                            break
                
                i += 1
            
            # SAVE VALID LISTINGS
            if listing['listing_title'] and listing['sold_price']:
                title = listing['listing_title']
                title = re.sub(r'\s+(Related:|Include description|View similar|Sell one like).*$', '', title, flags=re.I)
                title = re.sub(r'\s+Direct from eBay.*$', '', title, flags=re.I)
                title = re.sub(r'\s{2,}', ' ', title)
                listing['listing_title'] = title.strip()
                
                listings.append(listing)
                print(f"    ✓ Valid listing: {listing['listing_title'][:60]}...")
            else:
                missing = []
                if not listing['listing_title']:
                    missing.append('title')
                if not listing['sold_price']:
                    missing.append('price')
                print(f"    ✗ Incomplete listing, missing: {', '.join(missing)}")
        
        print(f"  ✓ Extracted {len(listings)} valid listings")
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
    
    existing_ids = set()
    all_listings = []
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('image_id', '') for item in data}
    
    print(f"Loaded {len(all_listings)} existing listings with {len(existing_ids)} unique image IDs\n")
    
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
            if skipped_count % 10 == 0:
                print(f"[Skipped {skipped_count} already processed images...]")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("\n✓ No new listings to add.")
    
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
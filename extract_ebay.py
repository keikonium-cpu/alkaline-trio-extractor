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
    """
    Extract eBay listings with precise pattern matching.
    Pattern: Sold/Ended Date → Title → Condition → Price → Seller
    """
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Extract text line by line
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"  OCR extracted {len(lines)} raw lines")
        
        listings = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # STEP 1: Find Sold/Ended date line
            date_match = re.match(
                r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
                line,
                re.I
            )
            
            if not date_match:
                i += 1
                continue
            
            # Start new listing
            listing = {
                'status': date_match.group(1).capitalize(),  # "Sold" or "Ended"
                'date': line,
                'listing_title': '',
                'sold_price': None,
                'seller': None
            }
            
            print(f"    [{listing['status']}] {line}")
            i += 1
            
            # STEP 2: Extract title (everything until condition or price)
            title_lines = []
            while i < len(lines):
                current = lines[i]
                
                # Stop conditions
                if re.match(r'^(Brand New|Pre-Owned|New with tags|New without tags|Open box|Used|For parts)$', current, re.I):
                    print(f"      Condition found: {current}")
                    i += 1
                    break
                
                # Price found without condition
                if re.match(r'^\$[\d,]+\.?\d{0,2}$', current):
                    print(f"      Price without condition: {current}")
                    break
                
                # Seller pattern (ends title)
                if re.search(r'\d+%\s*positive', current, re.I):
                    print(f"      Seller pattern found: {current}")
                    break
                
                # Skip eBay UI elements
                skip_patterns = [
                    r'^(Buy It Now|or Best Offer|Make Offer|Auction|Bids?:)',
                    r'^(Located in|Shipping|Delivery|Returns)',
                    r'^(Authenticity Guarantee|Top Rated)',
                    r'^\d+\s*(bid|watcher)',
                    r'^Free',
                    r'^Watch',
                ]
                
                should_skip = False
                for pattern in skip_patterns:
                    if re.search(pattern, current, re.I):
                        should_skip = True
                        break
                
                if should_skip:
                    i += 1
                    continue
                
                # Valid title line
                title_lines.append(current)
                print(f"      Title: {current}")
                i += 1
            
            listing['listing_title'] = ' '.join(title_lines).strip()
            
            # STEP 3: Find price (large font, starts with $)
            while i < len(lines):
                current = lines[i]
                
                price_match = re.match(r'^\$[\d,]+\.?\d{0,2}$', current)
                if price_match:
                    listing['sold_price'] = current
                    print(f"      Price: {current}")
                    i += 1
                    break
                
                i += 1
                
                # Safety: don't search too far
                if i - date_match.start() > 20:
                    break
            
            # STEP 4: Find seller (appears near price, before next listing)
            # Seller format: username followed by rating (XX% positive)
            # Located on same horizontal line as price or within next few lines
            seller_search_start = i
            while i < len(lines) and i < seller_search_start + 8:
                current = lines[i]
                
                # Stop if we hit the next listing
                if re.match(r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', current, re.I):
                    break
                
                # Pattern 1: seller name WITH rating on same line
                # E.g., "username 98% positive (123)" or "username98% positive"
                seller_match = re.search(
                    r'^(.+?)\s*(\d+)%\s*(?:positive|feedback)',
                    current,
                    re.I
                )
                
                if seller_match:
                    seller_name = seller_match.group(1).strip()
                    # Remove common prefixes/suffixes
                    seller_name = re.sub(r'^(by|from|seller:?)\s+', '', seller_name, flags=re.I)
                    listing['seller'] = seller_name
                    print(f"      Seller: {listing['seller']}")
                    i += 1
                    break
                
                # Pattern 2: seller name alone, rating on next line
                # Must not be price, date, or common eBay text
                if (not re.match(r'^\
            
            # Only save valid listings
            if listing['listing_title'] and listing['sold_price']:
                # Clean title
                title = listing['listing_title']
                # Remove trailing junk
                title = re.sub(r'\s+(Related:|Include description|View similar|Sell one like|Extra \d+%).*$', '', title, flags=re.I)
                title = re.sub(r'\s+Direct from eBay.*$', '', title, flags=re.I)
                listing['listing_title'] = title.strip()
                
                listings.append(listing)
                print(f"    ✓ Valid listing: {listing['listing_title'][:60]}...")
            else:
                print(f"    ✗ Incomplete listing, skipping")
        
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
            if skipped_count % 10 == 0:  # Less verbose
                print(f"[Skipped {skipped_count} already processed images...]")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("\n✓ No new listings to add.")
    
    # Save JSON
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
, current) and 
                    not re.match(r'^(Located|Shipping|Buy|or Best|Free|Watch|Bid)', current, re.I) and
                    not re.match(r'^\d+\s*(bid|watcher)', current, re.I)):
                    
                    # Peek ahead for rating on next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if re.search(r'\d+%\s*(?:positive|feedback)', next_line, re.I):
                            seller_name = current.strip()
                            seller_name = re.sub(r'^(by|from|seller:?)\s+', '', seller_name, flags=re.I)
                            listing['seller'] = seller_name
                            print(f"      Seller (split): {listing['seller']}")
                            i += 2
                            break
                
                i += 1
            
            # Only save valid listings
            if listing['listing_title'] and listing['sold_price']:
                # Clean title
                title = listing['listing_title']
                # Remove trailing junk
                title = re.sub(r'\s+(Related:|Include description|View similar|Sell one like|Extra \d+%).*$', '', title, flags=re.I)
                title = re.sub(r'\s+Direct from eBay.*$', '', title, flags=re.I)
                listing['listing_title'] = title.strip()
                
                listings.append(listing)
                print(f"    ✓ Valid listing: {listing['listing_title'][:60]}...")
            else:
                print(f"    ✗ Incomplete listing, skipping")
        
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
            if skipped_count % 10 == 0:  # Less verbose
                print(f"[Skipped {skipped_count} already processed images...]")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
    else:
        print("\n✓ No new listings to add.")
    
    # Save JSON
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
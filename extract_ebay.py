import json
import re
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time

def extract_ebay_listings_direct():
    """Extract listings directly from eBay search results using Selenium."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        driver = webdriver.Chrome(options=chrome_options)
        
        all_listings = []
        
        # Start with first page
        base_url = "https://www.ebay.com/sch/i.html?_nkw=alkaline+trio&LH_Complete=1&LH_Sold=1&_ipg=240&_pgn="
        
        for page in range(1, 6):  # Get first 5 pages (up to 1200 listings)
            url = base_url + str(page)
            print(f"\nFetching page {page}: {url}")
            driver.get(url)
            time.sleep(3)
            
            try:
                # Wait for listings to load
                wait = WebDriverWait(driver, 15)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".s-item")))
                
                # Get all listing items
                items = driver.find_elements(By.CSS_SELECTOR, ".s-item")
                print(f"Found {len(items)} items on page {page}")
                
                for item in items:
                    try:
                        # Skip the header item
                        if "s-item--header" in item.get_attribute("class"):
                            continue
                        
                        listing = {
                            'status': None,
                            'date': None,
                            'listing_title': None,
                            'sold_price': None,
                            'seller': None,
                            'processed_at': datetime.now().isoformat()
                        }
                        
                        # Extract title
                        try:
                            title_elem = item.find_element(By.CSS_SELECTOR, ".s-item__title")
                            listing['listing_title'] = title_elem.text.strip()
                        except:
                            continue
                        
                        # Extract price
                        try:
                            price_elem = item.find_element(By.CSS_SELECTOR, ".s-item__price")
                            price_text = price_elem.text.strip()
                            # Clean price (take first price if range)
                            price_match = re.search(r'\$[\d,]+\.?\d{0,2}', price_text)
                            if price_match:
                                listing['sold_price'] = price_match.group()
                        except:
                            pass
                        
                        # Extract seller
                        try:
                            seller_elem = item.find_element(By.CSS_SELECTOR, ".s-item__seller-info-text")
                            seller_text = seller_elem.text.strip()
                            listing['seller'] = seller_text
                        except:
                            pass
                        
                        # Extract status and date from subtitle
                        try:
                            subtitle_elem = item.find_element(By.CSS_SELECTOR, ".s-item__subtitle, .POSITIVE")
                            subtitle_text = subtitle_elem.text.strip()
                            
                            # Look for "Sold" or "Ended" with date
                            date_match = re.search(r'(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', subtitle_text, re.I)
                            if date_match:
                                listing['status'] = date_match.group(1).capitalize()
                                listing['date'] = date_match.group(0)
                        except:
                            pass
                        
                        # Default status to Sold if not found
                        if not listing['status']:
                            listing['status'] = 'Sold'
                        
                        # Only save if we have minimum required data
                        if listing['listing_title'] and listing['sold_price']:
                            all_listings.append(listing)
                            print(f"  ✓ {listing['listing_title'][:50]}... | {listing['sold_price']}")
                        
                    except Exception as e:
                        print(f"  ✗ Error parsing item: {e}")
                        continue
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                break
        
        driver.quit()
        print(f"\n✓ Extracted {len(all_listings)} total listings")
        return all_listings
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            driver.quit()
        except:
            pass
        return []

def update_listings():
    """Main function - extract from eBay directly."""
    output_json = 'listings.json'
    
    # Load existing listings
    existing_listings = []
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            existing_listings = json.load(f)
    
    print(f"Loaded {len(existing_listings)} existing listings\n")
    
    # Extract new listings
    new_listings = extract_ebay_listings_direct()
    
    if not new_listings:
        print("No new listings extracted")
        return False
    
    # Merge with existing (avoid duplicates by title+price)
    existing_keys = {(l.get('listing_title'), l.get('sold_price')) for l in existing_listings}
    unique_new = []
    
    for listing in new_listings:
        key = (listing.get('listing_title'), listing.get('sold_price'))
        if key not in existing_keys:
            unique_new.append(listing)
            existing_keys.add(key)
    
    if unique_new:
        all_listings = existing_listings + unique_new
        print(f"\n✓ Added {len(unique_new)} new listings. Total: {len(all_listings)}")
    else:
        all_listings = existing_listings
        print(f"\n✓ No new unique listings found")
    
    # Save
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=4)
    
    print(f"✓ Saved to {output_json}")
    return len(unique_new) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Changes ready for commit")
    else:
        print("\n✓ No changes to commit")
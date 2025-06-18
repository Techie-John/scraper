# Import necessary libraries
import gradio as gr          # For creating the web-based graphical user interface (GUI)
import requests              # For making HTTP requests to fetch web pages (used for fallback/link discovery)
from bs4 import BeautifulSoup # For parsing HTML documents (used for generic link discovery)
import html2text             # For converting HTML content to Markdown format
import PyPDF2                # For extracting text from PDF files
import re                    # For regular expressions (used for minor text cleaning and URL validation)
import json                  # For working with JSON data (input/output format)
from urllib.parse import urlparse, urljoin # For parsing, joining, and normalizing URLs
import os                    # For operating system related functionalities (e.g., getting file basename)
import time                  # For adding delays to be polite to web servers
from collections import deque # For implementing a queue for URL processing

# Import the 'trafilatura' library for generic article extraction.
# This is the core component that enables "no custom code" for websites.
try:
    import trafilatura
except ImportError:
    print("Error: 'trafilatura' library not found. Please install it by running: pip install trafilatura")
    # Provide a dummy function to allow the script to be parsed even if the library isn't installed.
    def trafilatura_extract(html, url, output_format, include_comments, include_links, include_formatting):
        raise NotImplementedError("trafilatura not installed. Please install it via 'pip install trafilatura'")
    def trafilatura_fetch_url(url):
        raise NotImplementedError("trafilatura not installed. Please install it via 'pip install trafilatura'")


# --- SECTION 1: CORE HELPER FUNCTIONS ---
# These functions perform fundamental tasks: fetching HTML, converting formats, and URL manipulation.

def get_html_content_basic(url):
    """
    Fetches raw HTML content from a given URL using requests.
    This is used as a fallback for `trafilatura.fetch_url` or specifically for
    discovering links on index pages (where `trafilatura`'s full article extraction
    isn't needed at this stage). Includes robust headers and timeouts.
    
    Args:
        url (str): The URL of the web page to fetch.
    
    Returns:
        str or None: The HTML content as a string if successful, otherwise None.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url} with basic requests: {e}")
        return None

def html_to_markdown(html_content):
    """
    Converts HTML content to a clean Markdown format.
    Used for both `trafilatura`'s extracted HTML and for fallback HTML content.
    Ensures that the output content meets the 'Markdown content' requirement.
    
    Args:
        html_content (str): The HTML string to convert.
        
    Returns:
        str: The converted Markdown string.
    """
    if not html_content:
        return ""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.body_width = 0
    h.unicode_snob = True
    h.skip_internal_links = True
    h.wrap_links = False
    h.mark_code = True
    
    markdown = h.handle(html_content)
    markdown = re.sub(r'\n\s*\n', '\n\n', markdown) # Clean up excessive blank lines
    return markdown.strip()

def extract_text_from_pdf(pdf_file_path):
    """
    Extracts plain text content from a PDF file using PyPDF2.
    Handles the ingestion of PDF documents, fulfilling the 'Aline's Book' requirement.
    
    Args:
        pdf_file_path (str): The path to the PDF file.
        
    Returns:
        str or None: The extracted text content, or None if an error occurs.
    """
    text = ""
    try:
        with open(pdf_file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page_num in range(len(reader.pages)):
                text += reader.pages[page_num].extract_text() + "\n\n"
        return text
    except Exception as e:
        print(f"Error extracting text from PDF {pdf_file_path}: {e}")
        return None

def get_base_domain(url):
    """
    Extracts the base domain from a URL, normalizing for common subdomains.
    This is used for filtering links to ensure we stay within the intended website
    or its relevant subdomains during link discovery.
    
    Args:
        url (str): The URL string.
        
    Returns:
        str: The normalized base domain (e.g., "example.com").
    """
    parsed_uri = urlparse(url)
    netloc = parsed_uri.netloc.replace('www.', '') # Remove 'www.'
    
    # Generic normalization for common blog/publishing platforms
    if netloc.endswith('.substack.com'):
        return 'substack.com'
    if netloc.endswith('.medium.com'):
        return 'medium.com'
    if netloc.endswith('.gitconnected.com'):
        return 'gitconnected.com'
    if netloc.endswith('.freecodecamp.org'):
        return 'freecodecamp.org'
    if netloc.endswith('.hubspot.com'): # For blog.hubspot.com
        return 'hubspot.com'

    return netloc

# --- SECTION 2: WEB ARTICLE EXTRACTION (GENERIC & RULE-FREE) ---
# This is where `trafilatura` shines, eliminating site-specific CSS selectors.

def scrape_web_article_generic(url):
    """
    Generically scrapes a web article using the `trafilatura` library.
    This function implements the "no custom code, no rules" principle for web content extraction.
    `trafilatura` automatically downloads, parses, and extracts the main content, title, authors,
    and other metadata from virtually any given article URL using advanced heuristics.
    
    Args:
        url (str): The URL of the web page to scrape.
        
    Returns:
        dict or None: A dictionary containing the scraped data
                      (title, content in Markdown, author, source_url, content_type='blog')
                      or None if scraping fails.
    """
    try:
        # trafilatura.fetch_url handles downloading with good defaults (user-agent, retries)
        downloaded_html = trafilatura.fetch_url(url)
        
        if not downloaded_html:
            print(f"Trafilatura failed to download HTML for {url}. Skipping this URL.")
            return None # Cannot proceed without HTML content

        # Use trafilatura.extract to get the main content and metadata.
        # output_format='json' is ideal as it gives us structured data directly.
        extracted_json_str = trafilatura.extract(
            downloaded_html,
            url=url, # Provide URL for better context for trafilatura's internal logic
            output_format='json',
            include_comments=False,    # Usually don't want comments in main article content
            include_links=True,        # Preserve links within the content
            include_formatting=True    # Preserve bold, italics, etc.
        )

        if not extracted_json_str:
            print(f"Trafilatura extracted no article data from {url}. Content might not be an article or site blocks extraction.")
            return None # If trafilatura finds no article, it's not an article for our purpose

        # Parse the JSON string into a Python dictionary
        parsed_data = json.loads(extracted_json_str)

        # Map trafilatura's output to the desired JSON format
        title = parsed_data.get("title", os.path.basename(urlparse(url).path.strip('/')) or url)
        authors = parsed_data.get("author", "Unknown")
        # trafilatura's 'text' field is often already clean or Markdown-like.
        # We pass it through html_to_markdown for consistency and extra cleanup.
        content_markdown = html_to_markdown(parsed_data.get("text", ""))

        return {
            "title": title,
            "content": content_markdown,
            "content_type": "blog", # Default for generic web articles
            "source_url": url,
            "author": authors,
            "user_id": "" # Placeholder: will be filled by `run_scraper_tool`
        }

    except Exception as e:
        print(f"An error occurred during generic web scraping for {url} with Trafilatura: {e}")
        return None

# --- SECTION 3: GENERIC LINK DISCOVERY (FOR "EVERY BLOG POST") ---
# This section enables the scraper to find and process multiple articles from index pages.

def get_all_links_from_page(url, base_domain):
    """
    Generically discovers all internal article-like links from a given web page.
    This function performs the "crawling" aspect, identifying URLs that likely
    point to individual articles. It's generic, relying on basic HTML parsing
    and URL heuristics, NOT site-specific CSS selectors for link identification.
    
    Args:
        url (str): The URL of the page (e.g., a blog index) to extract links from.
        base_domain (str): The normalized base domain of the current scraping session
                           to filter for internal links.
                           
    Returns:
        set: A set of unique, absolute URLs that are potential article links.
    """
    html_content = get_html_content_basic(url)
    if not html_content:
        return set() # Return empty set if page can't be fetched

    soup = BeautifulSoup(html_content, 'html.parser')
    found_urls = set()

    # Find all anchor (<a>) tags on the page
    for link_tag in soup.find_all('a', href=True):
        href = link_tag['href']
        full_url = urljoin(url, href) # Resolve relative URLs

        # Basic filtering to ensure it's a valid HTTP(S) link and not a fragment
        if not full_url.startswith(('http://', 'https://')):
            continue
        if '#' in full_url and not full_url.startswith(url + '#'): # Allow internal anchors on same page
            continue # Skip fragment links that aren't on the same page

        # Crucial: Filter for links that stay within the same base domain or a relevant subdomain.
        # This prevents the crawler from spiraling out to unrelated websites.
        link_domain = get_base_domain(full_url)
        if link_domain != base_domain:
            continue # Skip external links

        # Further simple heuristic: Exclude common non-article file extensions.
        # This is generic and helps avoid media files, zips, etc.
        if re.search(r'\.(pdf|docx|xlsx|zip|rar|tar|gz|jpg|jpeg|png|gif|svg|mp3|mp4|avi|mov)$', full_url, re.IGNORECASE):
            continue

        # More refined path filtering: Try to avoid common navigational/non-article paths.
        # This is a generic heuristic, not specific to any site's design.
        parsed_link_path = urlparse(full_url).path.lower()
        if (parsed_link_path.endswith('/') and len(parsed_link_path.strip('/')) < 5) or \
           '/category/' in parsed_link_path or \
           '/tag/' in parsed_link_path or \
           '/archive/' in parsed_link_path or \
           '/about' in parsed_link_path or \
           '/contact' in parsed_link_path or \
           '/privacy' in parsed_link_path:
           continue


        found_urls.add(full_url) # Add the filtered, absolute URL

    return found_urls

# --- SECTION 4: GRADIO INTERFACE FUNCTIONS & DEFINITION ---
# This section sets up the web UI using Gradio and orchestrates the overall
# data ingestion process based on user inputs.

def run_scraper_tool(team_id, user_id, urls_input, pdf_file_obj):
    """
    The main function for the Gradio interface. It manages a queue of URLs
    to process, handling both direct article URLs and index pages (by
    discovering links from them). All content is extracted generically.
    
    Args:
        team_id (str): The team identifier provided by the user.
        user_id (str): The user identifier for attributing scraped items.
        urls_input (str): A comma-separated string of initial URLs to scrape.
        pdf_file_obj (gradio.inputs.File or None): Gradio file object representing an uploaded PDF.
                                                    
    Returns:
        dict: The final output JSON structure containing all scraped items.
    """
    final_output = {
        "team_id": team_id if team_id else "default_team_id",
        "items": []
    }
    
    # Use a deque for efficient appends/pops (queue-like behavior)
    url_queue = deque()
    # Keep track of URLs that have been added to the queue OR already processed
    processed_urls = set() 
    
    scraped_count = 0

    # 1. Add initial URLs to the queue
    if urls_input:
        initial_urls = [u.strip() for u in urls_input.split(',') if u.strip()]
        for url in initial_urls:
            if url.startswith(('http://', 'https://')) and url not in processed_urls:
                url_queue.append(url)
                processed_urls.add(url)
            else:
                print(f"Skipping invalid or duplicate initial URL: {url}")

    # 2. Process URLs from the queue
    while url_queue:
        current_url = url_queue.popleft() # Get the next URL from the front of the queue
        print(f"Processing URL: {current_url}")
        
        # Determine the base domain for link discovery
        current_base_domain = get_base_domain(current_url)

        try:
            # First, try to scrape it as a generic article using Trafilatura
            item = scrape_web_article_generic(current_url)
            
            if item:
                # If Trafilatura successfully extracted an article, add it to output
                item["user_id"] = user_id if user_id else "default_user"
                final_output["items"].append(item)
                scraped_count += 1
                print(f"  -> Successfully scraped: {item['title']} from {current_url}")
            else:
                # If Trafilatura did NOT find an article (e.g., it's an index page, or site blocked it)
                # Then, attempt to discover links from this page
                print(f"  -> Trafilatura found no article. Attempting generic link discovery from: {current_url}")
                discovered_links = get_all_links_from_page(current_url, current_base_domain)
                
                # Add newly discovered, unprocessed links to the queue
                for link in discovered_links:
                    if link not in processed_urls:
                        url_queue.append(link)
                        processed_urls.add(link)
                        print(f"    -> Discovered link: {link}")
            
        except Exception as e:
            print(f"An unhandled error occurred while processing URL {current_url}: {e}")
            
        time.sleep(1) # Be polite: pause briefly between processing different URLs

    # 3. Process PDF File (if uploaded)
    if pdf_file_obj:
        print(f"Processing PDF file: {pdf_file_obj.name}")
        pdf_content = extract_text_from_pdf(pdf_file_obj.name)
        if pdf_content:
            pdf_title = os.path.basename(pdf_file_obj.name).replace(".pdf", "").replace("_", " ").title()
            final_output["items"].append({
                "title": f"{pdf_title} (Book Chapters)",
                "content": pdf_content,
                "content_type": "book",
                "source_url": "Aline's Book (Google Drive)",
                "author": "Aline",
                "user_id": user_id if user_id else "default_user"
            })
            scraped_count += 1
            print(f"  -> Successfully processed PDF: {pdf_title}")
        else:
            print(f"Could not extract content from PDF: {pdf_file_obj.name}")

    print(f"Scraping complete. Total items scraped: {scraped_count}")
    return final_output

# Define the Gradio interface layout and behavior
iface = gr.Interface(
    fn=run_scraper_tool,
    inputs=[
        gr.Textbox(
            label="Team ID",
            placeholder="e.g., aline123 (Required)",
            value="aline123"
        ),
        gr.Textbox(
            label="User ID (for scraped items)",
            placeholder="e.g., aline, jane_smith, my_team_member",
            value="aline"
        ),
        gr.Textbox(
            label="URLs to Scrape (Comma-separated)",
            placeholder="""
            Enter URLs here. This can be:
            - **Direct Article Links:** e.g., https://medium.com/@datawookie/web-scraping-with-python-and-beautiful-soup-c7ad2a234509
            - **Blog/Category Index Pages:** The tool will discover articles from these.
              e.g., https://interviewing.io/blog, https://nilmamano.com/blog/category/dsa
            - **Other Example Articles (current as of June 2025):**
              - freeCodeCamp: https://www.freecodecamp.org/news/how-to-code-snake-game-javascript/
              - Substack: https://jessmartin.substack.com/p/building-an-ai-powered-search-engine
              - TechCrunch: https://techcrunch.com/2024/06/18/eu-launches-ai-office-to-implement-ai-act-and-drive-global-collaboration/
              - The Verge: https://www.theverge.com/2024/6/18/24180424/apple-wwdc-2024-ai-iphone-ios-18-mac-features-takeaways (Note: NyTimes often blocks)
              - Wired: https://www.wired.com/story/apple-ai-intelligence-ios-18-macos-sonoma-privacy/
            """,
            lines=8
        ),
        gr.File(
            label="Upload PDF Book (Optional - First 8 Chapters)",
            type="filepath",
            file_types=[".pdf"]
        )
    ],
    outputs=gr.JSON(label="Scraped Data Output (JSON)"),
    title="📚 Knowledgebase Scraper: Truly Scalable & Rule-Free Content Ingestion �",
    description="""

    """
)

# --- SECTION 5: APPLICATION ENTRY POINT ---
# This block ensures the Gradio interface launches when the script is run directly.
if __name__ == "__main__":
    iface.launch(debug=True) # `debug=True` provides more verbose output in the console

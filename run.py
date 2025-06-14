# Import necessary libraries
import gradio as gr          # For creating the web-based graphical user interface (GUI)
import requests              # For making HTTP requests to fetch web pages
from bs4 import BeautifulSoup # For parsing HTML and XML documents
import html2text             # For converting HTML content to Markdown format
import PyPDF2                # For extracting text from PDF files
import re                    # For regular expressions (used for URL pattern matching)
import json                  # For working with JSON data (input/output format)
from urllib.parse import urlparse, urljoin # For parsing and joining URLs
import os                    # For operating system related functionalities (e.g., getting file basename)
import time                  # For adding delays to be polite to web servers

# --- SECTION 1: WEBSITE CONFIGURATION RULES ---
# This is the core of the scraper's adaptability and robustness.
# It's a dictionary that defines how to scrape different types of content
# from various websites.
#
# Structure:
# {
#   "domain.com": {                       # Top-level key is the normalized domain (e.g., "medium.com")
#     "page_type_key": {                  # Inner key describes a specific type of page on that domain
#       "url_pattern": "regex_pattern",   # Regex to match URLs belonging to this page type
#       "scrape_type": "index_to_articles" | "single_article", # How to handle this URL
#       "link_selector": "CSS_selector",  # (Only for "index_to_articles") Selector for links to articles
#       "title_selector": "CSS_selector" | ["CSS_selector1", "CSS_selector2"], # Selector(s) for the article title
#       "content_selector": "CSS_selector" | ["CSS_selector1", "CSS_selector2"],# Selector(s) for the main content
#       "author_selector": "CSS_selector" | ["CSS_selector1", "CSS_selector2"],# Selector(s) for the author name
#       "content_type": "blog" | "podcast_transcript" | "book" | "other" # Type for the output JSON
#     },
#     ... another page type config for domain.com ...
#   },
#   "another-domain.com": { ... }
# }
#
# Robustness via List of Selectors:
# For 'title_selector', 'content_selector', and 'author_selector', you can provide
# a LIST of CSS selectors. The `get_element_text` and `get_element_html` helper
# functions (defined below) will try each selector in the list IN ORDER until
# they find a matching element. This makes the scraper resilient to minor
# website layout changes (e.g., a class name changes, but an alternative selector still works).
#
# How to find CSS Selectors:
# 1. Open the webpage in your browser.
# 2. Right-click on the element you want to scrape (e.g., the article title, a paragraph of content).
# 3. Select "Inspect" or "Inspect Element".
# 4. In the browser's developer tools, find a unique CSS selector for that element.
#    You can right-click the element in the Elements tab, then "Copy" -> "Copy selector".
#    However, often it's better to find a more general selector (e.g., `h1`, `article`, `div.post-content`).
WEBSITE_CONFIG = {
    "interviewing.io": {
        "blog_index": {
            "url_pattern": r"https://interviewing\.io/blog/?$",
            "scrape_type": "index_to_articles",
            "link_selector": "a.blog-post-card-link", # Selector for individual blog post links on the index page
            "content_type": "blog"
        },
        "blog_article": {
            "url_pattern": r"https://interviewing\.io/blog/[^/]+/?$",
            "scrape_type": "single_article",
            "title_selector": "h1",
            "content_selector": [".blog-post-content", "div.html-content", "div.markdown-content"], # Prioritized content selectors
            "author_selector": ".author-name",
            "content_type": "blog"
        },
        "topics_index": {
            "url_pattern": r"https://interviewing\.io/topics/?$",
            "scrape_type": "index_to_articles",
            "link_selector": "#companies a.resource-card", # Selector for links within the 'companies' section
            "content_type": "other" # Categorized as 'other' as it's a company guide, not a blog post
        },
        "learn_index": {
            "url_pattern": r"https://interviewing\.io/learn/?$",
            "scrape_type": "index_to_articles",
            "link_selector": "#interview-guides a.resource-card", # Selector for links within the 'interview-guides' section
            "content_type": "other" # Categorized as 'other' as it's an interview guide
        },
        "guide_article": {
            "url_pattern": r"https://interviewing\.io/(?:topics|learn)/[^/]+/?$",
            "scrape_type": "single_article",
            "title_selector": "h1",
            "content_selector": ["div.html-content", "div.markdown-content"],
            "author_selector": None, # Authors not typically listed on these guides, so None
            "content_type": "other"
        }
    },
    "nilmamano.com": {
        "dsa_blog_index": {
            "url_pattern": r"https://nilmamano\.com/blog/category/dsa/?$",
            "scrape_type": "index_to_articles",
            "link_selector": "article h2.entry-title a", # Selector for article links on DSA blog category page
            "content_type": "blog"
        },
        "dsa_blog_article": {
            "url_pattern": r"https://nilmamano\.com/blog/[^/]+/[^/]+/?$", # Matches /blog/year/month/slug
            "scrape_type": "single_article",
            "title_selector": "h1.entry-title",
            "content_selector": ".entry-content",
            "author_selector": ".author",
            "content_type": "blog"
        }
    },
    "substack.com": { # Bonus: Substack support. Handles various substack authors.
        "generic_post": {
            "url_pattern": r"https://[a-zA-Z0-9-]+\.substack\.com/p/[^/]+/?$", # Matches any substack post
            "scrape_type": "single_article",
            "title_selector": "h1.post-title",
            "content_selector": "div.html-content", # Common content wrapper for substack posts
            "author_selector": ".byline-text",
            "content_type": "blog"
        }
    },
    "medium.com": { # Added for testing robustness with another popular platform
        "article": {
            "url_pattern": r"https://medium\.com/(@[\w\d-]+)?/[^/]+-[\w\d]+/?$", # Pattern for typical Medium articles
            "scrape_type": "single_article",
            "title_selector": "h1",
            # Prioritized content selectors for Medium (try most specific first, then broader semantic tags)
            "content_selector": ["div[data-testid='post-content']", "article", "div.pw-post-body-paragraph"],
            "author_selector": "a[data-testid='authorName']", # A common selector for author name
            "content_type": "blog"
        }
    },
    "freecodecamp.org": { # Added for testing robustness
        "news_article": {
            "url_pattern": r"https://www\.freecodecamp\.org/news/[^/]+/?$",
            "scrape_type": "single_article",
            "title_selector": "h1.post-full-title",
            "content_selector": "section.post-content",
            "author_selector": "a.author-card-name",
            "content_type": "blog"
        }
    },
    "gitconnected.com": { # Added for testing robustness with another popular dev blog platform
        "levelup_article": {
            "url_pattern": r"https://levelup\.gitconnected\.com/[^/]+-[a-f0-9]+/?$", # Pattern for LevelUp articles
            "scrape_type": "single_article",
            "title_selector": "h1.entry-title",
            "content_selector": "div.entry-content",
            "author_selector": ".author-name a",
            "content_type": "blog"
        }
    }
}

# --- SECTION 2: HELPER FUNCTIONS FOR ROBUST SELECTOR APPLICATION ---
# These functions abstract away the logic of trying multiple CSS selectors.

def get_element_text(soup_obj, selectors):
    """
    Helper function to try a list of CSS selectors (or a single selector string)
    on a BeautifulSoup object and return the stripped text of the first matching
    element found. This improves robustness by trying alternatives if a primary
    selector fails.
    
    Args:
        soup_obj (BeautifulSoup): The BeautifulSoup object to search within.
        selectors (str or list): A single CSS selector string or a list of
                                 CSS selector strings to try.
    
    Returns:
        str: The stripped text content of the first matching element,
             or an empty string if no element matches any selector.
    """
    # If a list of selectors is provided, iterate through them
    if isinstance(selectors, list):
        for selector in selectors:
            element = soup_obj.select_one(selector) # select_one finds the first match
            if element:
                return element.get_text(strip=True) # Return text if found
    elif selectors: # If it's a single string selector (not a list)
        element = soup_obj.select_one(selectors)
        if element:
            return element.get_text(strip=True)
    return "" # Return empty string if no match found for any selector

def get_element_html(soup_obj, selectors):
    """
    Helper function to try a list of CSS selectors (or a single selector string)
    on a BeautifulSoup object and return the HTML content of the first matching
    element found. Useful for extracting larger content blocks that will then
    be converted to Markdown.
    
    Args:
        soup_obj (BeautifulSoup): The BeautifulSoup object to search within.
        selectors (str or list): A single CSS selector string or a list of
                                 CSS selector strings to try.
    
    Returns:
        str: The HTML content of the first matching element,
             or an empty string if no element matches any selector.
    """
    if isinstance(selectors, list):
        for selector in selectors:
            element = soup_obj.select_one(selector)
            if element:
                return str(element) # Return HTML string if found
    elif selectors:
        element = soup_obj.select_one(selectors)
        if element:
            return str(element)
    return ""

# --- SECTION 3: GENERAL HELPER FUNCTIONS ---
# These functions handle common tasks like fetching HTML, converting formats, and URL parsing.

def get_html_content(url):
    """
    Fetches HTML content from a given URL using HTTP GET request.
    Includes a User-Agent header to mimic a web browser and a longer timeout
    for better robustness against slow server responses.
    
    Args:
        url (str): The URL of the web page to fetch.
    
    Returns:
        str or None: The HTML content as a string if successful, otherwise None.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Increased timeout to 30 seconds to handle slower website responses
        response = requests.get(url, headers=headers, timeout=30)
        # Raise an HTTPError for bad responses (4xx or 5xx client/server errors)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        # Catch any request-related exceptions (e.g., connection error, timeout, HTTP error)
        print(f"Error fetching URL {url}: {e}")
        return None

def html_to_markdown(html_content):
    """
    Converts HTML content to a clean Markdown format.
    Configured to preserve links and images and handle code blocks,
    while removing excessive blank lines for better readability.
    
    Args:
        html_content (str): The HTML string to convert.
        
    Returns:
        str: The converted Markdown string.
    """
    if not html_content:
        return ""
    h = html2text.HTML2Text()
    h.ignore_links = False     # Keep links in Markdown
    h.ignore_images = False    # Keep image references
    h.body_width = 0           # Disable line wrapping for content
    h.unicode_snob = True      # Prefer unicode characters for symbols (e.g., bullet points)
    h.skip_internal_links = True # Do not convert internal HTML links (e.g., #anchor-id)
    h.wrap_links = False       # Do not wrap links in newlines
    h.mark_code = True         # Attempt to identify and format code blocks
    
    markdown = h.handle(html_content)
    # Clean up excessive blank lines generated by html2text for cleaner output
    markdown = re.sub(r'\n\s*\n', '\n\n', markdown)
    return markdown.strip()

def extract_text_from_pdf(pdf_file_path):
    """
    Extracts text content from a PDF file using PyPDF2.
    
    Args:
        pdf_file_path (str): The path to the PDF file.
        
    Returns:
        str or None: The extracted text content as a string, or None if an error occurs.
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

def get_domain(url):
    """
    Extracts the normalized domain from a URL.
    This function is crucial for matching URLs to the `WEBSITE_CONFIG`
    even if they use subdomains (e.g., 'user.substack.com' should map to 'substack.com').
    
    Args:
        url (str): The URL string.
        
    Returns:
        str: The normalized domain (e.g., "example.com").
    """
    parsed_uri = urlparse(url)
    netloc = parsed_uri.netloc.replace('www.', '') # Remove 'www.' for consistency
    
    # Special handling for common platforms with dynamic subdomains
    if netloc.endswith('.substack.com'):
        return 'substack.com'
    if netloc.endswith('.medium.com'):
        return 'medium.com'
    if netloc.endswith('.gitconnected.com'):
        return 'gitconnected.com'

    return netloc

def match_url_to_config(url):
    """
    Attempts to match a given URL to a corresponding configuration
    in the `WEBSITE_CONFIG` dictionary.
    
    Args:
        url (str): The URL to match.
        
    Returns:
        tuple: A tuple containing (domain, config_key, config_details)
               if a match is found, otherwise (None, None, None).
    """
    domain = get_domain(url)
    if domain in WEBSITE_CONFIG:
        # Iterate through all configurations for that domain
        for config_key, config_details in WEBSITE_CONFIG[domain].items():
            # Check if the URL matches the defined regex pattern for this specific page type
            if re.match(config_details["url_pattern"], url):
                return domain, config_key, config_details
    return None, None, None # No matching configuration found

# --- SECTION 4: MAIN SCRAPING LOGIC FUNCTIONS ---
# These functions implement the core logic for scraping single articles and index pages.

def scrape_single_article(url, config_details):
    """
    Scrapes content from a single article page based on the provided configuration.
    It uses the robust `get_element_text` and `get_element_html` helpers.
    
    Args:
        url (str): The URL of the article to scrape.
        config_details (dict): The specific configuration dictionary for this page type.
        
    Returns:
        dict or None: A dictionary containing the scraped data in the desired
                      JSON format, or None if the HTML content could not be fetched.
    """
    html_content = get_html_content(url)
    if not html_content:
        return None # Cannot proceed without HTML content

    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Initialize the item data structure
    item_data = {
        "title": "Untitled", # Default title
        "content": "",
        "content_type": config_details.get("content_type", "other"),
        "source_url": url,
        "author": "",
        "user_id": "" # Placeholder, filled by `run_scraper_tool`
    }

    # 1. Extract Title: Use the robust helper to find the title
    item_data["title"] = get_element_text(soup, config_details.get("title_selector", ""))
    if not item_data["title"]:
        print(f"Warning: No title found for {url} with selectors {config_details.get('title_selector')}")
        # Fallback: Use URL path segment as title if no title element found
        item_data["title"] = os.path.basename(urlparse(url).path.strip('/')) or url

    # 2. Extract Content: Get the HTML of the content section, then convert to Markdown
    content_html = get_element_html(soup, config_details.get("content_selector", ""))
    if content_html:
        item_data["content"] = html_to_markdown(content_html)
    else:
        print(f"Warning: No content found for {url} with selectors {config_details.get('content_selector')}")

    # 3. Extract Author: Use the robust helper to find the author
    item_data["author"] = get_element_text(soup, config_details.get("author_selector", ""))

    return item_data

def scrape_index_page_and_articles(url, config_details):
    """
    Scrapes an index page (e.g., a blog category page), finds links to individual articles
    on that page, and then proceeds to scrape each linked article.
    
    Args:
        url (str): The URL of the index page to scrape.
        config_details (dict): The configuration for this index page type.
        
    Returns:
        list: A list of dictionaries, where each dictionary represents a scraped article.
    """
    print(f"Scraping index page: {url}")
    html_content = get_html_content(url)
    if not html_content:
        return [] # Cannot proceed without HTML content

    soup = BeautifulSoup(html_content, 'html.parser')
    scraped_items = []
    
    # Find all potential article links on the index page using the link_selector
    links = soup.select(config_details.get("link_selector", ""))
    
    # Use a set to keep track of processed URLs and avoid duplicate scraping
    processed_urls = set()

    for link_tag in links:
        href = link_tag.get('href')
        if not href:
            continue # Skip if no href attribute

        # Resolve relative URLs (e.g., "/blog/my-post" to "https://example.com/blog/my-post")
        full_url = urljoin(url, href)
        
        # Basic validation: ensure it's a valid HTTP/HTTPS URL and not just a page fragment or internal link
        if not full_url.startswith(('http://', 'https://')):
            continue

        # Avoid processing the same URL multiple times (important for robustness)
        if full_url in processed_urls:
            continue
        processed_urls.add(full_url)
        
        # Match the found full URL to an article configuration (e.g., blog_article, guide_article)
        _, _, article_config = match_url_to_config(full_url)
        
        # If a matching single_article configuration is found, scrape it
        if article_config and article_config["scrape_type"] == "single_article":
            print(f"  -> Scraping linked article: {full_url}")
            article_data = scrape_single_article(full_url, article_config)
            if article_data:
                scraped_items.append(article_data)
            time.sleep(0.5) # Be polite: pause briefly between requests to the same domain
        else:
            # Inform if a link is skipped because it's not a configured article type
            print(f"  -> Skipping non-article link or unconfigured URL: {full_url}")

    return scraped_items

def process_url(url):
    """
    Determines the type of URL (single article or index page) and
    initiates the appropriate scraping process based on `WEBSITE_CONFIG`.
    
    Args:
        url (str): The URL to process.
        
    Returns:
        list: A list of scraped item dictionaries. Returns an empty list
              if no configuration is found or scraping fails.
    """
    # Try to match the URL to one of the predefined configurations
    domain, config_key, config_details = match_url_to_config(url)
    
    if not config_details:
        print(f"Error: No specific scraping configuration found for URL: {url}")
        # For this assignment, we choose to return an empty list if not explicitly configured.
        # This signals that the tool understands the URL but doesn't know how to parse it.
        return [] 

    # Based on the scrape_type in the matched configuration, call the appropriate scraper function
    if config_details["scrape_type"] == "single_article":
        item = scrape_single_article(url, config_details)
        return [item] if item else [] # Return a list containing the single item, or an empty list
    elif config_details["scrape_type"] == "index_to_articles":
        return scrape_index_page_and_articles(url, config_details)
    else:
        # Should not be reached if config_details are well-defined
        print(f"Unknown scrape_type: {config_details['scrape_type']} for URL: {url}")
        return []

# --- SECTION 5: GRADIO INTERFACE FUNCTIONS & DEFINITION ---
# This section sets up the web UI using Gradio and orchestrates the overall scraping process.

def run_scraper_tool(team_id, user_id, urls_input, pdf_file_obj):
    """
    The main function that acts as the backend for the Gradio interface.
    It takes user inputs (team ID, user ID, URLs, PDF file) and orchestrates
    the scraping and processing to generate the final JSON output.
    
    Args:
        team_id (str): The team identifier for the output JSON.
        user_id (str): The user identifier for the output JSON.
        urls_input (str): A comma-separated string of URLs to scrape.
        pdf_file_obj (gradio.inputs.File or None): Object representing the uploaded PDF file.
                                                    Contains .name attribute for the temporary file path.
                                                    
    Returns:
        dict: The final output JSON structure containing all scraped items.
    """
    final_output = {
        "team_id": team_id if team_id else "default_team_id", # Use provided team_id or a default
        "items": []
    }
    
    scraped_count = 0 # Counter for successfully scraped items

    # Process Web URLs (if provided)
    if urls_input:
        # Split the comma-separated string into a list of URLs and clean whitespace
        urls = [u.strip() for u in urls_input.split(',') if u.strip()]
        for url in urls:
            print(f"Processing URL: {url}")
            try:
                # Call the core URL processing logic
                items = process_url(url)
                for item in items:
                    if item: # Ensure the item dictionary is not None
                        item["user_id"] = user_id if user_id else "default_user" # Assign the user_id
                        final_output["items"].append(item)
                        scraped_count += 1
            except Exception as e:
                # Catch any unexpected errors during URL processing
                print(f"An error occurred while processing URL {url}: {e}")
            time.sleep(1) # Polite delay between processing different top-level URLs

    # Process PDF File (if uploaded)
    if pdf_file_obj:
        print(f"Processing PDF file: {pdf_file_obj.name}")
        pdf_content = extract_text_from_pdf(pdf_file_obj.name)
        if pdf_content:
            # Generate a title from the PDF filename
            pdf_title = os.path.basename(pdf_file_obj.name).replace(".pdf", "").replace("_", " ").title()
            final_output["items"].append({
                "title": f"{pdf_title} (Book Chapters)", # Indicate it's from the book
                "content": pdf_content,
                "content_type": "book",
                "source_url": "Aline's Book (Google Drive)", # As per problem description
                "author": "Aline", # Assumed author, could be made configurable if needed
                "user_id": user_id if user_id else "default_user" # Assign the user_id
            })
            scraped_count += 1
        else:
            print(f"Could not extract content from PDF: {pdf_file_obj.name}")

    print(f"Scraping complete. Total items scraped: {scraped_count}")
    return final_output # Return the accumulated JSON output

# Define the Gradio interface
# This creates the UI elements and links them to the `run_scraper_tool` function.
iface = gr.Interface(
    fn=run_scraper_tool, # The Python function to call when the user interacts with the UI
    inputs=[
        gr.Textbox(
            label="Team ID",
            placeholder="e.g., aline123 (Required)",
            value="aline123" # Pre-fill for convenience during demo
        ),
        gr.Textbox(
            label="User ID (for scraped items)",
            placeholder="e.g., aline, jane_smith, my_team_member",
            value="aline" # Default to 'aline' for original problem context, but editable
        ),
        gr.Textbox(
            label="URLs to Scrape (Comma-separated)",
            placeholder="""
            Example URLs (try these to showcase robustness!):
            - Medium: https://medium.com/datawookie/web-scraping-with-python-and-beautiful-soup-c7ad2a234509
            - freeCodeCamp: https://www.freecodecamp.org/news/learn-javascript-for-beginners/
            - Substack: https://jessmartin.substack.com/p/the-importance-of-side-projects
            - LevelUp GitConnected: https://levelup.gitconnected.com/when-elegant-code-leads-to-untraceable-bugs-a-case-study-in-abstraction-8af2b117ecca
            """,
            lines=8 # Allows multiple lines for easier input of many URLs
        ),
        gr.File(
            label="Upload PDF Book (Optional - First 8 Chapters)",
            type="filepath", # Gradio handles the file upload and provides a temporary path
            file_types=[".pdf"] # Restrict uploads to PDF files
        )
    ],
    outputs=gr.JSON(label="Scraped Data Output (JSON)"), # Output component to display the JSON result
    title="📚 Knowledgebase Scraper for Technical Content 🤖", # Title of the Gradio application
    description="""
    This tool scrapes technical content from specified URLs (blogs, guides, Substack, Medium, freeCodeCamp)
    and PDF files, converting it into a structured JSON format.
    <br>
    <!-- HTML for detailed explanation of robustness and extensibility directly in the Gradio description -->
    <div style="padding: 15px; border: 1px solid #ccc; border-radius: 8px; margin-top: 15px; background-color: #f9f9f9;">
        <h4 style="color: #333; margin-top: 0;">On Robustness & Extensibility (Key Design Principles):</h4>
        <p style="color: #555;">
            The scraper's design prioritizes **reusability and adaptability**. The <code>WEBSITE_CONFIG</code> dictionary is key to this:
            <ul>
                <li><strong>Configuration-Driven:</strong> Each website has its own set of rules (URL patterns, content types, CSS selectors). Adding support for a new website simply means adding a new entry to this dictionary, without needing to modify the core scraping logic. This enables rapid expansion for future customers.</li>
                <li><strong>Robust Selectors (Lists of Selectors):</strong> For critical elements like <code>title</code>, <code>content</code>, and <code>author</code>, you can now provide a <strong>list of CSS selectors</strong>. The scraper will try them in order until one matches. This makes the tool significantly more resilient to minor website layout changes over time. If a class name changes, an alternative selector can still work, preventing immediate breakage.</li>
                <li><strong>Semantic & Broad Selectors:</strong> Whenever possible, we aim for general HTML tags (e.g., <code>&lt;article&gt;</code>, <code>&lt;h1&gt;</code>) or stable HTML attributes like <code>id</code>. These are generally less prone to change than highly specific or auto-generated class names, enhancing long-term stability.</li>
                <li><strong>Domain Normalization:</strong> The tool intelligently normalizes domain names (e.g., mapping <code>user.substack.com</code> to <code>substack.com</code> or <code>blog.medium.com</code> to <code>medium.com</code>). This means one configuration entry can cover many subdomains of a popular platform.</li>
            </ul>
            This modular, configuration-driven approach allows for efficient development, rapid adaptation to new content sources, and graceful handling of website updates.
        </p>
    </div>
    """
)

# --- SECTION 6: APPLICATION ENTRY POINT ---
# This block ensures the Gradio interface launches when the script is run directly.
if __name__ == "__main__":
    iface.launch(debug=True) # `debug=True` provides more verbose output in the console

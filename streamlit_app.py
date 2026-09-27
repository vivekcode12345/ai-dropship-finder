"""Streamlit frontend for the Viral Product Hunter application."""
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("BACKEND_API_URL") or "http://127.0.0.1:8000"
BACKEND_READ_TIMEOUT = int(os.getenv("BACKEND_READ_TIMEOUT", "600"))
TIMEOUT = (10, BACKEND_READ_TIMEOUT)

st.set_page_config(page_title="Viral Product Hunter AI", layout="wide")
st.title("Viral Product Hunter AI")

niche = st.text_input("Enter a product niche:", value="pet gadgets")

debug_mode = st.checkbox("Show Debug Data", value=False)

if st.button("Hunt Products", type="primary"):
    try:
        # Initialize session state for staged results
        if "hunt_results" not in st.session_state:
            st.session_state.hunt_results = {}
        
        # Clear old results
        st.session_state.hunt_results = {}
        
        status_placeholder = st.status("Discovering products...")
        status_placeholder.write("Discovering products and ranking with AI...")
        
        # Step 1: POST to /discover
        try:
            discover_response = requests.post(
                f"{API_URL}/discover",
                json={"niche": niche},
                timeout=TIMEOUT
            )
            discover_response.raise_for_status()
            discover_result = discover_response.json()
        except requests.exceptions.RequestException as e:
            status_placeholder.error(f"Discovery failed: {e}")
            st.error(f"Failed to connect to the backend: {e}")
            st.error(f"Please start FastAPI at {API_URL}")
            st.stop()
        
        # Store discovery result
        st.session_state.hunt_results = {
            **discover_result,
            "stage": "discover_completed"
        }
        
        # Report how many initial candidates were ranked
        initial_count = len(discover_result.get("initial_products", []))
        status_placeholder.write(f"Discovery complete: {initial_count} candidates ranked")
        
        # Step 2: Update status for sourcing
        status_placeholder.write("Sourcing Alibaba and AliExpress offers...")
        
        # Step 2: POST to /source
        initial_products = discover_result.get("initial_products", [])
        try:
            source_response = requests.post(
                f"{API_URL}/source",
                json={"niche": niche, "initial_products": initial_products},
                timeout=TIMEOUT
            )
            source_response.raise_for_status()
            source_result = source_response.json()
        except requests.exceptions.RequestException as e:
            status_placeholder.error(f"Sourcing failed: {e}")
            st.error(f"Failed to connect to the backend: {e}")
            st.error(f"Please start FastAPI at {API_URL}")
            st.stop()
        
        # Merge both responses
        merged_result = {
            "niche": niche,
            "message": "Viral product hunt complete - discovery, AI ranking, supplier sourcing, and final ranking done",
            "initial_products": discover_result.get("initial_products", []),
            "final_products": source_result.get("final_products", []),
            "supplier_summary": source_result.get("supplier_summary", {}),
            "supplier_data": source_result.get("supplier_data", []),
            "discovery_summary": discover_result.get("discovery_summary", []),
            "discovery_data": discover_result.get("discovery_data", []),
            "ranking_warnings": discover_result.get("ranking_warnings", []) + source_result.get("ranking_warnings", []),
        }
        
        # Store merged result in session state
        st.session_state.hunt_results = merged_result
        
        # Mark status complete
        status_placeholder.write("Complete!")
        status_placeholder.update(
            label="Viral product hunt complete",
            state="complete",
            expanded=False,
        )
        
        # Get the merged result for display
        result = merged_result

    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.stop()

# Display results if available
if "hunt_results" in st.session_state and st.session_state.hunt_results:
    result = st.session_state.hunt_results
    
    # Show ranking warnings
    if result.get("ranking_warnings"):
        for warning in result["ranking_warnings"]:
            st.warning(warning)

    # 1. Initial Viral Ranking
    if result.get("initial_products"):
        st.subheader("1. Initial Viral Ranking")
        products_data = result["initial_products"]
        if products_data:
            products_table = []
            for rank, p in enumerate(products_data, start=1):
                url = p.get("url", "")
                # Create clickable link if URL exists
                product_display = p.get("product", "")
                if url:
                    product_display = f"[{product_display}]({url})"

                price_str = ""
                price = p.get("price")
                currency = p.get("currency", "")
                if price is not None:
                    price_str = f"{currency} {price:.2f}" if currency else f"{price:.2f}"

                products_table.append({
                    "Rank": rank,
                    "Product": product_display,
                    "Viral Score": p.get("viral_score", 0),
                    "Retail Price": price_str,
                    "Currency": currency,
                    "Source": p.get("source", ""),
                    "URL": url,
                })
            st.table(products_table)

    # 2. Supplier Sourcing
    st.subheader("2. Supplier Sourcing")
    supplier_summary = result.get("supplier_summary", {})
    
    # Show metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Products Validated", supplier_summary.get("products_validated", 0))
    with col2:
        st.metric("Total Requests", supplier_summary.get("total_supplier_requests", 0))
    with col3:
        st.metric("Successful", supplier_summary.get("successful_supplier_requests", 0))
    with col4:
        st.metric("Failed", supplier_summary.get("failed_supplier_requests", 0))
    with col5:
        st.metric("Empty", supplier_summary.get("empty_supplier_requests", 0))

    # Show supplier data
    supplier_data = result.get("supplier_data", [])
    if supplier_data:
        for product_supplier in supplier_data:
            product_name = product_supplier.get("product_name", "Unknown Product")
            with st.expander(f"Supplier offers for: {product_name}", expanded=False):
                supplier_results = product_supplier.get("supplier_results", [])
                if supplier_results:
                    supplier_table = []
                    for sr in supplier_results:
                        offer = sr.get("offer", {})
                        platform = sr.get("platform", "")
                        
                        # Price display
                        price_str = ""
                        unit_price = offer.get("unit_price")
                        price_range = offer.get("price_range")
                        currency = offer.get("currency", "")
                        
                        if price_range:
                            min_price = price_range.get("min", 0)
                            max_price = price_range.get("max", 0)
                            if min_price and max_price:
                                price_str = f"{currency} {min_price:.2f} - {max_price:.2f}"
                        elif unit_price is not None:
                            price_str = f"{currency} {unit_price:.2f}" if isinstance(unit_price, (int, float)) else str(unit_price)
                        
                        # MOQ
                        moq = offer.get("min_order_quantity", "")
                        
                        # Rating
                        rating = offer.get("rating", "")
                        if isinstance(rating, (int, float)):
                            rating = f"{rating:.1f}"
                        
                        # Orders
                        orders = offer.get("orders", "")
                        
                        # Supplier URL
                        supplier_url = offer.get("supplier_url", "")
                        url_display = supplier_url
                        if supplier_url:
                            url_display = f"[{supplier_url}]({supplier_url})"
                        
                        supplier_table.append({
                            "Platform": platform,
                            "Listing": offer.get("supplier_title", ""),
                            "Price": price_str,
                            "Currency": currency,
                            "MOQ": moq,
                            "Shipping": offer.get("shipping_info", ""),
                            "Rating": rating,
                            "Orders": orders,
                            "Supplier Link": url_display,
                        })
                    st.table(supplier_table)
                else:
                    st.info("No supplier offers found for this product.")

    # 3. Final Supplier-Aware Ranking
    st.subheader("3. Final Supplier-Aware Ranking")
    final_products = result.get("final_products", [])
    if final_products:
        final_table = []
        for rank, p in enumerate(final_products, start=1):
            # Product display
            product_display = p.get("product", "")
            url = p.get("url", "")
            if url:
                product_display = f"[{product_display}]({url})"
            
            # Supplier offer display
            supplier_offer = p.get("selected_supplier_offer", {})
            if supplier_offer:
                supplier_title = supplier_offer.get("supplier_title", "")
                supplier_url = supplier_offer.get("supplier_url", "")
                supplier_display = f"[{supplier_title}]({supplier_url})" if supplier_url else supplier_title
                
                # Price USD
                price_usd = supplier_offer.get("price_usd")
                price_usd_str = f"${price_usd:.2f}" if price_usd is not None else "N/A"
                
                # MOQ
                moq = supplier_offer.get("min_order_quantity", "")
                
                # Reasoning and rejection
                reasoning = p.get("supplier_price_reasoning", "")
                rejection = p.get("rejection_reason", "")
                
                final_table.append({
                    "Rank": rank,
                    "Product": product_display,
                    "Final Score": f"{p.get('final_score', 0):.2f}",
                    "Selected Supplier": supplier_display,
                    "Supplier Cost (USD)": price_usd_str,
                    "MOQ": moq,
                    "Reasoning": reasoning[:100],
                    "Rejection": rejection[:50],
                })
            else:
                # No supplier selected
                reasoning = p.get("supplier_price_reasoning", "")
                rejection = p.get("rejection_reason", "")
                
                final_table.append({
                    "Rank": rank,
                    "Product": product_display,
                    "Final Score": f"{p.get('final_score', 0):.2f}",
                    "Selected Supplier": "None",
                    "Supplier Cost (USD)": "N/A",
                    "MOQ": "N/A",
                    "Reasoning": reasoning[:100],
                    "Rejection": rejection[:100],
                })
        
        st.table(final_table)
    else:
        st.info("No final products ranked yet.")

    # Discovery source details
    st.subheader("Discovery source details")
    
    # Show source summary table
    if result.get("discovery_summary"):
        summary_data = result["discovery_summary"]
        if summary_data:
            summary_table = []
            for s in summary_data:
                summary_table.append({
                    "Source": s.get("source", ""),
                    "Error": s.get("error", ""),
                    "Products": s.get("product_count", 0),
                    "Status": s.get("parser_status", ""),
                    "Blocked": "Yes" if s.get("robot_blocked") else "No",
                    "Preview": s.get("preview", "")[:100],
                })
            st.table(summary_table)

    # Show debug data
    if debug_mode:
        st.subheader("Debug: Full Response")
        st.json(result)

        if "discovery_data" in result and result["discovery_data"]:
            with st.expander("Debug: Compact Discovery Data", expanded=False):
                st.json(result["discovery_data"])

else:
    # No results yet, show instructions
    st.info("Click 'Hunt Products' to start the product research process.")

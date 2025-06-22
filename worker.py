# --- START OF FILE worker.py ---

import sqlite3
import logging
import os
import re
from datetime import datetime, timezone
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import telegram.error as telegram_error

# Import necessary items from utils
from utils import (
    CITIES, DISTRICTS, PRODUCT_TYPES, ADMIN_ID, LANGUAGES, 
    SIZES, format_currency, send_message_with_retry,
    get_db_connection, MEDIA_DIR, is_worker,
    load_all_data, _get_lang_data, DEFAULT_PRODUCT_EMOJI
)

# Setup logger for this file
logger = logging.getLogger(__name__)

# --- Worker Panel Main Menu ---
async def handle_worker_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays the worker panel for workers to add drops."""
    user = update.effective_user
    query = update.callback_query
    
    if not user:
        logger.warning("handle_worker_panel triggered without effective_user.")
        if query: 
            await query.answer("Error: Could not identify user.", show_alert=True)
        return

    user_id = user.id
    chat_id = update.effective_chat.id

    # Check if user is a worker
    if not is_worker(user_id):
        logger.warning(f"Non-worker user {user_id} attempted to access worker panel.")
        msg = "❌ Access denied. You are not authorized to access the worker panel."
        if query: 
            await query.answer(msg, show_alert=True)
        else: 
            await send_message_with_retry(context.bot, chat_id, msg, parse_mode=None)
        return

    # Worker panel menu
    msg = f"👷 Worker Panel\n\nWelcome, @{user.username or 'Worker'}!\n\nYou can add drops to existing product types:"
    
    keyboard = [
        [InlineKeyboardButton("📦 Add Single Drop", callback_data="worker_add_drop")],
        [InlineKeyboardButton("📦📦 Bulk Add Drops", callback_data="worker_bulk_add")],
        [InlineKeyboardButton("❌ Close", callback_data="close_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=None)
        except telegram_error.BadRequest:
            # If edit fails, send new message
            await send_message_with_retry(context.bot, chat_id, msg, reply_markup=reply_markup, parse_mode=None)
    else:
        await send_message_with_retry(context.bot, chat_id, msg, reply_markup=reply_markup, parse_mode=None)

# --- Worker Add Drop Flow ---
async def handle_worker_add_drop(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Start the worker add drop flow - select city."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    load_all_data()  # Ensure fresh data
    
    if not CITIES:
        await query.edit_message_text("❌ No cities available. Contact admin to add cities first.", parse_mode=None)
        return
    
    msg = "🏙️ Select City\n\nChoose a city to add drops to:"
    keyboard = []
    
    for city_id, city_name in CITIES.items():
        keyboard.append([InlineKeyboardButton(city_name, callback_data=f"worker_city|{city_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Worker Panel", callback_data="worker_panel")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selected city - show districts."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid city selection.", show_alert=True)
    
    city_id = params[0]
    if city_id not in CITIES:
        return await query.answer("City not found.", show_alert=True)
    
    city_name = CITIES[city_id]
    context.user_data['worker_city_id'] = city_id
    context.user_data['worker_city_name'] = city_name
    
    # Get districts for this city
    city_districts = DISTRICTS.get(city_id, {})
    if not city_districts:
        await query.edit_message_text(f"❌ No districts available in {city_name}. Contact admin to add districts first.", parse_mode=None)
        return
    
    msg = f"🏘️ Select District in {city_name}\n\nChoose a district:"
    keyboard = []
    
    for district_id, district_name in city_districts.items():
        keyboard.append([InlineKeyboardButton(district_name, callback_data=f"worker_district|{district_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_add_drop")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_district(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selected district - show product types."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid district selection.", show_alert=True)
    
    district_id = params[0]
    city_id = context.user_data.get('worker_city_id')
    
    if not city_id or city_id not in DISTRICTS:
        return await query.answer("City data lost. Please start over.", show_alert=True)
    
    city_districts = DISTRICTS[city_id]
    if district_id not in city_districts:
        return await query.answer("District not found.", show_alert=True)
    
    district_name = city_districts[district_id]
    city_name = context.user_data.get('worker_city_name')
    
    context.user_data['worker_district_id'] = district_id
    context.user_data['worker_district_name'] = district_name
    
    if not PRODUCT_TYPES:
        await query.edit_message_text("❌ No product types available. Contact admin to add product types first.", parse_mode=None)
        return
    
    msg = f"💎 Select Product Type\n\nCity: {city_name}\nDistrict: {district_name}\n\nChoose a product type:"
    keyboard = []
    
    for product_type, emoji in PRODUCT_TYPES.items():
        display_text = f"{emoji} {product_type}"
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f"worker_type|{product_type}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"worker_city|{city_id}")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selected product type - show size options."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid product type selection.", show_alert=True)
    
    product_type = params[0]
    if product_type not in PRODUCT_TYPES:
        return await query.answer("Product type not found.", show_alert=True)
    
    city_name = context.user_data.get('worker_city_name')
    district_name = context.user_data.get('worker_district_name')
    
    context.user_data['worker_product_type'] = product_type
    
    emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
    msg = f"📏 Select Size\n\nCity: {city_name}\nDistrict: {district_name}\nType: {emoji} {product_type}\n\nChoose a size:"
    
    keyboard = []
    for size in SIZES:
        keyboard.append([InlineKeyboardButton(size, callback_data=f"worker_size|{size}")])
    
    keyboard.append([InlineKeyboardButton("✏️ Custom Size", callback_data="worker_custom_size")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Types", callback_data=f"worker_district|{context.user_data.get('worker_district_id')}")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selected size - ask for drop details."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid size selection.", show_alert=True)
    
    size = params[0]
    context.user_data['worker_size'] = size
    context.user_data['state'] = 'awaiting_worker_drop_details'
    
    city_name = context.user_data.get('worker_city_name')
    district_name = context.user_data.get('worker_district_name')
    product_type = context.user_data.get('worker_product_type')
    emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
    
    msg = (f"📝 Enter Drop Details\n\n"
           f"City: {city_name}\n"
           f"District: {district_name}\n"
           f"Type: {emoji} {product_type}\n"
           f"Size: {size}\n\n"
           f"Please send the drop details (name/description and media):")
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="worker_panel")]]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Send drop details in chat.")

async def handle_worker_custom_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker wants to enter custom size."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    context.user_data['state'] = 'awaiting_worker_custom_size'
    
    msg = "✏️ Enter Custom Size\n\nPlease type the custom size (e.g., '2.5g', 'Large', etc.):"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="worker_panel")]]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter custom size in chat.")

# --- Worker Message Handlers ---
async def handle_worker_custom_size_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom size input from worker."""
    if not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    if not is_worker(user_id):
        return
    
    custom_size = update.message.text.strip()
    if not custom_size:
        await send_message_with_retry(context.bot, update.effective_chat.id, "❌ Size cannot be empty. Please try again.", parse_mode=None)
        return
    
    context.user_data['worker_size'] = custom_size
    context.user_data['state'] = 'awaiting_worker_drop_details'
    
    city_name = context.user_data.get('worker_city_name')
    district_name = context.user_data.get('worker_district_name')
    product_type = context.user_data.get('worker_product_type')
    emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
    
    msg = (f"📝 Enter Drop Details\n\n"
           f"City: {city_name}\n"
           f"District: {district_name}\n"
           f"Type: {emoji} {product_type}\n"
           f"Size: {custom_size}\n\n"
           f"Please send the drop details (name/description and media):")
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="worker_panel")]]
    
    await send_message_with_retry(context.bot, update.effective_chat.id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_drop_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drop details message from worker."""
    if not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    if not is_worker(user_id):
        return
    
    # Collect drop details from the message
    original_text = update.message.text or update.message.caption or ""
    
    # Store the media and details for confirmation
    context.user_data['worker_drop_text'] = original_text
    context.user_data['worker_drop_media'] = []
    
    # Process media if present
    if update.message.photo:
        context.user_data['worker_drop_media'].append({
            'type': 'photo',
            'file_id': update.message.photo[-1].file_id
        })
    elif update.message.video:
        context.user_data['worker_drop_media'].append({
            'type': 'video',
            'file_id': update.message.video.file_id
        })
    elif update.message.animation:
        context.user_data['worker_drop_media'].append({
            'type': 'animation',
            'file_id': update.message.animation.file_id
        })
    
    # Now ask for price
    context.user_data['state'] = 'awaiting_worker_price'
    
    msg = "💰 Enter Price\n\nPlease enter the price for this drop in EUR (e.g., 25.50):"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="worker_panel")]]
    
    await send_message_with_retry(context.bot, update.effective_chat.id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_price_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle price input from worker."""
    if not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    if not is_worker(user_id):
        return
    
    price_text = update.message.text.strip()
    
    try:
        price = float(price_text)
        if price <= 0:
            await send_message_with_retry(context.bot, update.effective_chat.id, "❌ Price must be greater than 0. Please try again.", parse_mode=None)
            return
        if price > 10000:
            await send_message_with_retry(context.bot, update.effective_chat.id, "❌ Price too high (max 10,000 EUR). Please try again.", parse_mode=None)
            return
    except ValueError:
        await send_message_with_retry(context.bot, update.effective_chat.id, "❌ Invalid price format. Please enter a number (e.g., 25.50).", parse_mode=None)
        return
    
    context.user_data['worker_price'] = price
    context.user_data['state'] = None
    
    # Show confirmation
    await show_worker_drop_confirmation(update, context)

async def show_worker_drop_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation for the worker's drop."""
    city_name = context.user_data.get('worker_city_name')
    district_name = context.user_data.get('worker_district_name')
    product_type = context.user_data.get('worker_product_type')
    size = context.user_data.get('worker_size')
    price = context.user_data.get('worker_price')
    drop_text = context.user_data.get('worker_drop_text', '')
    drop_media = context.user_data.get('worker_drop_media', [])
    
    emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
    
    msg = (f"✅ Confirm Drop Addition\n\n"
           f"City: {city_name}\n"
           f"District: {district_name}\n"
           f"Type: {emoji} {product_type}\n"
           f"Size: {size}\n"
           f"Price: {format_currency(price)} EUR\n"
           f"Description: {drop_text[:100]}{'...' if len(drop_text) > 100 else ''}\n"
           f"Media: {len(drop_media)} file(s)\n\n"
           f"Add this drop?")
    
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Add Drop", callback_data="worker_confirm_add_drop")],
        [InlineKeyboardButton("❌ Cancel", callback_data="worker_panel")]
    ]
    
    await send_message_with_retry(context.bot, update.effective_chat.id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_confirm_add_drop(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Confirm and add the worker's drop to the database."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    # Get all the stored data
    city_id = context.user_data.get('worker_city_id')
    city_name = context.user_data.get('worker_city_name')
    district_id = context.user_data.get('worker_district_id')
    district_name = context.user_data.get('worker_district_name')
    product_type = context.user_data.get('worker_product_type')
    size = context.user_data.get('worker_size')
    price = context.user_data.get('worker_price')
    drop_text = context.user_data.get('worker_drop_text', '')
    drop_media = context.user_data.get('worker_drop_media', [])
    
    if not all([city_id, city_name, district_id, district_name, product_type, size, price is not None]):
        await query.answer("Missing data. Please start over.", show_alert=True)
        return
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Add the product
            c.execute("""
                INSERT INTO products (city, district, product_type, size, name, price, available, reserved, original_text, added_by, added_date)
                VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
            """, (city_name, district_name, product_type, size, drop_text, price, drop_text, user_id, datetime.now(timezone.utc).isoformat()))
            
            product_id = c.lastrowid
            
            # Save media files
            saved_media_count = 0
            for media_item in drop_media:
                try:
                    file_id = media_item['file_id']
                    media_type = media_item['type']
                    
                    # Get file from Telegram
                    file = await context.bot.get_file(file_id)
                    
                    # Create filename
                    extension = 'jpg' if media_type == 'photo' else ('mp4' if media_type == 'video' else 'gif')
                    filename = f"product_{product_id}_{saved_media_count + 1}.{extension}"
                    file_path = os.path.join(MEDIA_DIR, filename)
                    
                    # Download file
                    await file.download_to_drive(file_path)
                    
                    # Save to database
                    c.execute("""
                        INSERT INTO product_media (product_id, media_type, file_path, telegram_file_id)
                        VALUES (?, ?, ?, ?)
                    """, (product_id, media_type, file_path, file_id))
                    
                    saved_media_count += 1
                    
                except Exception as e:
                    logger.error(f"Error saving media for product {product_id}: {e}")
            
            conn.commit()
            
            # Clear worker data
            worker_keys = [k for k in context.user_data.keys() if k.startswith('worker_')]
            for key in worker_keys:
                context.user_data.pop(key, None)
            
            emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
            success_msg = (f"✅ Drop Added Successfully!\n\n"
                          f"Product ID: {product_id}\n"
                          f"Location: {city_name}, {district_name}\n"
                          f"Type: {emoji} {product_type}\n"
                          f"Size: {size}\n"
                          f"Price: {format_currency(price)} EUR\n"
                          f"Media files: {saved_media_count}")
            
            keyboard = [[InlineKeyboardButton("👷 Back to Worker Panel", callback_data="worker_panel")]]
            
            await query.edit_message_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
            
            logger.info(f"Worker {user_id} added drop {product_id}: {product_type} in {city_name}, {district_name}")
            
    except sqlite3.Error as e:
        logger.error(f"Database error adding worker drop: {e}", exc_info=True)
        await query.answer("❌ Database error. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error adding worker drop: {e}", exc_info=True)
        await query.answer("❌ An error occurred. Please try again.", show_alert=True)

# --- Worker Bulk Add Flow ---
async def handle_worker_bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Start worker bulk add flow."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    msg = (f"📦📦 Bulk Add Drops\n\n"
           f"This feature allows you to add multiple drops of the same type to the same location.\n\n"
           f"First, select the location and product type, then you'll be able to add multiple drops with different sizes and prices.\n\n"
           f"Ready to start?")
    
    keyboard = [
        [InlineKeyboardButton("✅ Start Bulk Add", callback_data="worker_bulk_city")],
        [InlineKeyboardButton("⬅️ Back to Worker Panel", callback_data="worker_panel")]
    ]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker bulk add - select city."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    load_all_data()
    
    if not CITIES:
        await query.edit_message_text("❌ No cities available. Contact admin to add cities first.", parse_mode=None)
        return
    
    msg = "🏙️ Bulk Add - Select City\n\nChoose a city:"
    keyboard = []
    
    for city_id, city_name in CITIES.items():
        keyboard.append([InlineKeyboardButton(city_name, callback_data=f"worker_bulk_city_selected|{city_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="worker_bulk_add")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_city_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker bulk add - city selected, show districts."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid city selection.", show_alert=True)
    
    city_id = params[0]
    if city_id not in CITIES:
        return await query.answer("City not found.", show_alert=True)
    
    city_name = CITIES[city_id]
    context.user_data['worker_bulk_city_id'] = city_id
    context.user_data['worker_bulk_city_name'] = city_name
    
    city_districts = DISTRICTS.get(city_id, {})
    if not city_districts:
        await query.edit_message_text(f"❌ No districts available in {city_name}. Contact admin to add districts first.", parse_mode=None)
        return
    
    msg = f"🏘️ Bulk Add - Select District in {city_name}\n\nChoose a district:"
    keyboard = []
    
    for district_id, district_name in city_districts.items():
        keyboard.append([InlineKeyboardButton(district_name, callback_data=f"worker_bulk_district|{district_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_bulk_city")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_district(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker bulk add - district selected, show product types."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid district selection.", show_alert=True)
    
    district_id = params[0]
    city_id = context.user_data.get('worker_bulk_city_id')
    
    if not city_id or city_id not in DISTRICTS:
        return await query.answer("City data lost. Please start over.", show_alert=True)
    
    city_districts = DISTRICTS[city_id]
    if district_id not in city_districts:
        return await query.answer("District not found.", show_alert=True)
    
    district_name = city_districts[district_id]
    city_name = context.user_data.get('worker_bulk_city_name')
    
    context.user_data['worker_bulk_district_id'] = district_id
    context.user_data['worker_bulk_district_name'] = district_name
    
    if not PRODUCT_TYPES:
        await query.edit_message_text("❌ No product types available. Contact admin to add product types first.", parse_mode=None)
        return
    
    msg = f"💎 Bulk Add - Select Product Type\n\nCity: {city_name}\nDistrict: {district_name}\n\nChoose a product type:"
    keyboard = []
    
    for product_type, emoji in PRODUCT_TYPES.items():
        display_text = f"{emoji} {product_type}"
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f"worker_bulk_type|{product_type}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"worker_bulk_city_selected|{city_id}")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker bulk add - product type selected, start bulk entry."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or not params[0]:
        return await query.answer("Invalid product type selection.", show_alert=True)
    
    product_type = params[0]
    if product_type not in PRODUCT_TYPES:
        return await query.answer("Product type not found.", show_alert=True)
    
    city_name = context.user_data.get('worker_bulk_city_name')
    district_name = context.user_data.get('worker_bulk_district_name')
    
    context.user_data['worker_bulk_product_type'] = product_type
    context.user_data['worker_bulk_drops'] = []
    context.user_data['state'] = 'awaiting_worker_bulk_messages'
    
    emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
    
    msg = (f"📦📦 Bulk Add Drops\n\n"
           f"City: {city_name}\n"
           f"District: {district_name}\n"
           f"Type: {emoji} {product_type}\n\n"
           f"Now send messages for each drop you want to add.\n"
           f"Each message should contain:\n"
           f"• Size and price (e.g., '1g - 25.50')\n"
           f"• Description/name\n"
           f"• Media (optional)\n\n"
           f"Send one message per drop. When finished, use the buttons below.")
    
    keyboard = [
        [InlineKeyboardButton("✅ Process All Drops", callback_data="worker_bulk_process")],
        [InlineKeyboardButton("❌ Cancel Bulk Add", callback_data="worker_panel")]
    ]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Send drop messages now.")

async def handle_worker_bulk_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk drop messages from worker."""
    if not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    if not is_worker(user_id):
        return
    
    text = update.message.text or update.message.caption or ""
    
    # Try to parse size and price from the text
    # Look for patterns like "1g - 25.50", "2g 30", "Large - 45.00", etc.
    price_pattern = r'(\d+(?:\.\d+)?)\s*(?:eur|euro|€)?\s*$'
    size_price_patterns = [
        r'^(.+?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:eur|euro|€)?\s*$',  # "1g - 25.50"
        r'^(.+?)\s+(\d+(?:\.\d+)?)\s*(?:eur|euro|€)?\s*$',         # "1g 25.50"
        r'^(\d+(?:\.\d+)?[a-zA-Z]*)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:eur|euro|€)?\s*$',  # "1g - 25.50"
    ]
    
    size = None
    price = None
    description = text
    
    for pattern in size_price_patterns:
        match = re.search(pattern, text.strip(), re.IGNORECASE)
        if match:
            size = match.group(1).strip()
            try:
                price = float(match.group(2))
                # Remove the size-price part from description
                description = re.sub(pattern, '', text.strip(), flags=re.IGNORECASE).strip()
                break
            except ValueError:
                continue
    
    if not size or price is None:
        await send_message_with_retry(context.bot, update.effective_chat.id, 
                                    "❌ Could not parse size and price. Please use format like '1g - 25.50' or '1g 25.50'", 
                                    parse_mode=None)
        return
    
    if price <= 0 or price > 10000:
        await send_message_with_retry(context.bot, update.effective_chat.id, 
                                    "❌ Price must be between 0 and 10,000 EUR.", 
                                    parse_mode=None)
        return
    
    # Process media
    media_items = []
    if update.message.photo:
        media_items.append({
            'type': 'photo',
            'file_id': update.message.photo[-1].file_id
        })
    elif update.message.video:
        media_items.append({
            'type': 'video',
            'file_id': update.message.video.file_id
        })
    elif update.message.animation:
        media_items.append({
            'type': 'animation',
            'file_id': update.message.animation.file_id
        })
    
    # Store the drop
    bulk_drops = context.user_data.get('worker_bulk_drops', [])
    bulk_drops.append({
        'size': size,
        'price': price,
        'description': description,
        'original_text': text,
        'media': media_items
    })
    context.user_data['worker_bulk_drops'] = bulk_drops
    
    # Send confirmation
    emoji = PRODUCT_TYPES.get(context.user_data.get('worker_bulk_product_type'), DEFAULT_PRODUCT_EMOJI)
    await send_message_with_retry(context.bot, update.effective_chat.id, 
                                f"✅ Drop {len(bulk_drops)} added: {emoji} {size} - {format_currency(price)} EUR", 
                                parse_mode=None)

async def handle_worker_bulk_process(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Process all bulk drops."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    bulk_drops = context.user_data.get('worker_bulk_drops', [])
    if not bulk_drops:
        await query.answer("No drops to process.", show_alert=True)
        return
    
    city_id = context.user_data.get('worker_bulk_city_id')
    city_name = context.user_data.get('worker_bulk_city_name')
    district_name = context.user_data.get('worker_bulk_district_name')
    product_type = context.user_data.get('worker_bulk_product_type')
    
    if not all([city_id, city_name, district_name, product_type]):
        await query.answer("Missing location data. Please start over.", show_alert=True)
        return
    
    try:
        added_count = 0
        total_media_count = 0
        
        with get_db_connection() as conn:
            c = conn.cursor()
            
            for drop in bulk_drops:
                size = drop['size']
                price = drop['price']
                description = drop['description']
                original_text = drop['original_text']
                media_items = drop['media']
                
                # Add the product
                c.execute("""
                    INSERT INTO products (city, district, product_type, size, name, price, available, reserved, original_text, added_by, added_date)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
                """, (city_name, district_name, product_type, size, description, price, original_text, user_id, datetime.now(timezone.utc).isoformat()))
                
                product_id = c.lastrowid
                added_count += 1
                
                # Save media files
                media_count = 0
                for media_item in media_items:
                    try:
                        file_id = media_item['file_id']
                        media_type = media_item['type']
                        
                        # Get file from Telegram
                        file = await context.bot.get_file(file_id)
                        
                        # Create filename
                        extension = 'jpg' if media_type == 'photo' else ('mp4' if media_type == 'video' else 'gif')
                        filename = f"product_{product_id}_{media_count + 1}.{extension}"
                        file_path = os.path.join(MEDIA_DIR, filename)
                        
                        # Download file
                        await file.download_to_drive(file_path)
                        
                        # Save to database
                        c.execute("""
                            INSERT INTO product_media (product_id, media_type, file_path, telegram_file_id)
                            VALUES (?, ?, ?, ?)
                        """, (product_id, media_type, file_path, file_id))
                        
                        media_count += 1
                        total_media_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error saving bulk media for product {product_id}: {e}")
            
            conn.commit()
        
        # Clear bulk data
        bulk_keys = [k for k in context.user_data.keys() if k.startswith('worker_bulk_')]
        for key in bulk_keys:
            context.user_data.pop(key, None)
        context.user_data.pop('state', None)
        
        emoji = PRODUCT_TYPES.get(product_type, DEFAULT_PRODUCT_EMOJI)
        success_msg = (f"🎉 Bulk Add Complete!\n\n"
                      f"✅ Added {added_count} drops\n"
                      f"📍 Location: {city_name}, {district_name}\n"
                      f"💎 Type: {emoji} {product_type}\n"
                      f"📸 Media files: {total_media_count}\n\n"
                      f"All drops have been successfully added to the inventory!")
        
        keyboard = [[InlineKeyboardButton("👷 Back to Worker Panel", callback_data="worker_panel")]]
        
        await query.edit_message_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        
        logger.info(f"Worker {user_id} bulk added {added_count} drops of {product_type} in {city_name}, {district_name}")
        
    except sqlite3.Error as e:
        logger.error(f"Database error in worker bulk add: {e}", exc_info=True)
        await query.answer("❌ Database error. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in worker bulk add: {e}", exc_info=True)
        await query.answer("❌ An error occurred. Please try again.", show_alert=True)

# --- Close Menu Handler ---
async def handle_close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Close the worker menu."""
    query = update.callback_query
    try:
        await query.delete_message()
    except telegram_error.BadRequest:
        await query.edit_message_text("Menu closed.", parse_mode=None)

# --- END OF FILE worker.py --- 
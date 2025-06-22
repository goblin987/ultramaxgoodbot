# --- START OF FILE worker.py ---

import os
import time
import shutil
import asyncio
import sqlite3
import re
from datetime import datetime, timezone
from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import telegram.error as telegram_error

from utils import (
    get_db_connection, format_currency, send_message_with_retry,
    is_worker, CITIES, DISTRICTS, PRODUCT_TYPES, DEFAULT_PRODUCT_EMOJI,
    SIZES, MEDIA_DIR, logger, _get_lang_data
)

# Worker Panel Functions

async def handle_worker_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker panel main menu."""
    user = update.effective_user
    query = update.callback_query
    
    if not user or not is_worker(user.id):
        msg = "❌ Access denied."
        if query: 
            await query.answer(msg, show_alert=True)
        return

    msg = f"👷 Worker Panel\n\nWelcome, @{user.username or 'Worker'}!\n\nYou can add drops to existing product types:"
    
    keyboard = [
        [InlineKeyboardButton("📦 Add Single Drop", callback_data="worker_city")],
        [InlineKeyboardButton("📦📦 Bulk Add Drops", callback_data="worker_bulk_city")],
        [InlineKeyboardButton("❌ Close", callback_data="close_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=None)
        except telegram_error.BadRequest:
            await send_message_with_retry(context.bot, update.effective_chat.id, msg, reply_markup=reply_markup, parse_mode=None)
    else:
        await send_message_with_retry(context.bot, update.effective_chat.id, msg, reply_markup=reply_markup, parse_mode=None)

# Worker functions that reuse admin logic
async def handle_worker_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker city selection - reuses admin logic."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    # Set worker context and call admin function directly
    context.user_data["is_worker"] = True
    context.user_data["worker_id"] = query.from_user.id
    
    # Call admin function with worker context
    lang, lang_data = _get_lang_data(context)
    if not CITIES:
        return await query.edit_message_text("No cities configured. Please contact an admin.", parse_mode=None)
    
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id, ''))
    keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c,'N/A')}", callback_data=f"worker_dist|{c}")] for c in sorted_city_ids]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="worker_panel")])
    
    select_city_text = lang_data.get("admin_select_city", "Select City to Add Product:")
    await query.edit_message_text(select_city_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_dist(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker district selection."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params: 
        return await query.answer("Error: City ID missing.", show_alert=True)
    
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found. Please select again.", parse_mode=None)
    
    districts_in_city = DISTRICTS.get(city_id, {})
    lang, lang_data = _get_lang_data(context)
    select_district_template = lang_data.get("admin_select_district", "Select District in {city}:")
    
    if not districts_in_city:
        keyboard = [[InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_city")]]
        return await query.edit_message_text(f"No districts found for {city_name}. Please contact an admin.",
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    
    sorted_district_ids = sorted(districts_in_city.keys(), key=lambda dist_id: districts_in_city.get(dist_id,''))
    keyboard = []
    for d in sorted_district_ids:
        dist_name = districts_in_city.get(d)
        if dist_name:
            keyboard.append([InlineKeyboardButton(f"🏘️ {dist_name}", callback_data=f"worker_type|{city_id}|{d}")])
        else: 
            logger.warning(f"District name missing for ID {d} in city {city_id}")
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_city")])
    select_district_text = select_district_template.format(city=city_name)
    await query.edit_message_text(select_district_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Close menu."""
    query = update.callback_query
    if query:
        try:
            await query.delete_message()
        except:
            await query.answer("Menu closed.")

# --- Worker Single Drop Functions (Reuse Admin Flow) ---
async def handle_worker_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects product type."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or len(params) < 2: 
        return await query.answer("Error: City or District ID missing.", show_alert=True)
    
    city_id, dist_id = params[0], params[1]
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    
    lang, lang_data = _get_lang_data(context)
    select_type_text = lang_data.get("admin_select_type", "Select Product Type:")
    
    if not PRODUCT_TYPES:
        return await query.edit_message_text("No product types configured. Contact admin to add types.", parse_mode=None)

    keyboard = []
    for type_name, emoji in sorted(PRODUCT_TYPES.items()):
        keyboard.append([InlineKeyboardButton(f"{emoji} {type_name}", callback_data=f"worker_add|{city_id}|{dist_id}|{type_name}")])

    keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"worker_dist|{city_id}")])
    await query.edit_message_text(select_type_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects size for the new product."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or len(params) < 3: 
        return await query.answer("Error: Location/Type info missing.", show_alert=True)
    
    city_id, dist_id, p_type = params
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    
    type_emoji = PRODUCT_TYPES.get(p_type, DEFAULT_PRODUCT_EMOJI)
    
    # Store context as admin functions do, but with worker prefix for separation
    context.user_data["admin_city_id"] = city_id
    context.user_data["admin_district_id"] = dist_id
    context.user_data["admin_product_type"] = p_type
    context.user_data["admin_city"] = city_name
    context.user_data["admin_district"] = district_name
    context.user_data["is_worker"] = True  # Flag to distinguish worker operations
    
    keyboard = [[InlineKeyboardButton(f"📏 {s}", callback_data=f"worker_size|{s}")] for s in SIZES]
    keyboard.append([InlineKeyboardButton("📏 Custom Size", callback_data="worker_custom_size")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Types", callback_data=f"worker_type|{city_id}|{dist_id}")])
    
    await query.edit_message_text(f"📦 Adding {type_emoji} {p_type} in {city_name} / {district_name}\n\nSelect size:", 
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles selection of a predefined size."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params: 
        return await query.answer("Error: Size missing.", show_alert=True)
    
    size = params[0]
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the product again.", parse_mode=None)
    
    context.user_data["pending_drop_size"] = size
    context.user_data["state"] = "awaiting_price"
    
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="worker_cancel_add")]]
    await query.edit_message_text(f"Size set to {size}. Please reply with the price (e.g., 12.50 or 12.5):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter price in chat.")

async def handle_worker_custom_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Custom Size' button press."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the product again.", parse_mode=None)
    
    context.user_data["state"] = "awaiting_custom_size"
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="worker_cancel_add")]]
    await query.edit_message_text("Please reply with the custom size (e.g., 10g, 1/4 oz):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter custom size in chat.")

# --- Worker Bulk Add Functions (Reuse Admin Flow) ---
async def handle_worker_bulk_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects city to add bulk products to."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    lang, lang_data = _get_lang_data(context)
    if not CITIES:
        return await query.edit_message_text("No cities configured. Please contact an admin.", parse_mode=None)
    
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id, ''))
    keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c,'N/A')}", callback_data=f"worker_bulk_dist|{c}")] for c in sorted_city_ids]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="worker_panel")])
    
    select_city_text = lang_data.get("admin_select_city", "Select City to Add Bulk Products:")
    await query.edit_message_text(f"📦 Bulk Add Products\n\n{select_city_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_dist(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects district for bulk products."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params: 
        return await query.answer("Error: City ID missing.", show_alert=True)
    
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found. Please select again.", parse_mode=None)
    
    districts_in_city = DISTRICTS.get(city_id, {})
    lang, lang_data = _get_lang_data(context)
    select_district_template = lang_data.get("admin_select_district", "Select District in {city}:")
    
    if not districts_in_city:
        keyboard = [[InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_bulk_city")]]
        return await query.edit_message_text(f"No districts found for {city_name}. Please contact an admin.",
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    
    sorted_district_ids = sorted(districts_in_city.keys(), key=lambda d_id: districts_in_city.get(d_id,''))
    keyboard = []
    for d in sorted_district_ids:
        dist_name = districts_in_city.get(d)
        if dist_name:
            keyboard.append([InlineKeyboardButton(f"🏘️ {dist_name}", callback_data=f"worker_bulk_type|{city_id}|{d}")])
        else: 
            logger.warning(f"District name missing for ID {d} in city {city_id}")
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="worker_bulk_city")])
    select_district_text = select_district_template.format(city=city_name)
    await query.edit_message_text(select_district_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects product type for bulk products."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or len(params) < 2: 
        return await query.answer("Error: City or District ID missing.", show_alert=True)
    
    city_id, dist_id = params[0], params[1]
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    
    lang, lang_data = _get_lang_data(context)
    select_type_text = lang_data.get("admin_select_type", "Select Product Type:")
    
    if not PRODUCT_TYPES:
        return await query.edit_message_text("No product types configured. Contact admin to add types.", parse_mode=None)

    keyboard = []
    for type_name, emoji in sorted(PRODUCT_TYPES.items()):
        keyboard.append([InlineKeyboardButton(f"{emoji} {type_name}", callback_data=f"worker_bulk_add|{city_id}|{dist_id}|{type_name}")])

    keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"worker_bulk_dist|{city_id}")])
    await query.edit_message_text(f"📦 Bulk Add Products - {city_name} / {district_name}\n\n{select_type_text}", 
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker selects size for the bulk products."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params or len(params) < 3: 
        return await query.answer("Error: Location/Type info missing.", show_alert=True)
    
    city_id, dist_id, p_type = params
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    
    type_emoji = PRODUCT_TYPES.get(p_type, DEFAULT_PRODUCT_EMOJI)
    
    # Store initial bulk product details (use same keys as admin for compatibility)
    context.user_data["bulk_admin_city_id"] = city_id
    context.user_data["bulk_admin_district_id"] = dist_id
    context.user_data["bulk_admin_product_type"] = p_type
    context.user_data["bulk_admin_city"] = city_name
    context.user_data["bulk_admin_district"] = district_name
    context.user_data["is_worker"] = True  # Flag to distinguish worker operations
    
    keyboard = [[InlineKeyboardButton(f"📏 {s}", callback_data=f"worker_bulk_size|{s}")] for s in SIZES]
    keyboard.append([InlineKeyboardButton("📏 Custom Size", callback_data="worker_bulk_custom_size")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Types", callback_data=f"worker_bulk_type|{city_id}|{dist_id}")])
    
    await query.edit_message_text(f"📦 Bulk Adding {type_emoji} {p_type} in {city_name} / {district_name}\n\nSelect size:", 
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_worker_bulk_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles selection of a predefined size for bulk products."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not params: 
        return await query.answer("Error: Size missing.", show_alert=True)
    
    size = params[0]
    if not all(k in context.user_data for k in ["bulk_admin_city", "bulk_admin_district", "bulk_admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the bulk products again.", parse_mode=None)
    
    context.user_data["bulk_pending_drop_size"] = size
    context.user_data["state"] = "awaiting_bulk_price"
    
    keyboard = [[InlineKeyboardButton("❌ Cancel Bulk Add", callback_data="worker_cancel_bulk_add")]]
    await query.edit_message_text(f"📦 Bulk Products - Size set to {size}. Please reply with the price (e.g., 12.50 or 12.5):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter price in chat.")

async def handle_worker_bulk_custom_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Custom Size' button press for bulk products."""
    query = update.callback_query
    if not is_worker(query.from_user.id): 
        return await query.answer("Access denied.", show_alert=True)
    
    if not all(k in context.user_data for k in ["bulk_admin_city", "bulk_admin_district", "bulk_admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the bulk products again.", parse_mode=None)
    
    context.user_data["state"] = "awaiting_bulk_custom_size"
    keyboard = [[InlineKeyboardButton("❌ Cancel Bulk Add", callback_data="worker_cancel_bulk_add")]]
    await query.edit_message_text("📦 Bulk Products - Please reply with the custom size (e.g., 10g, 1/4 oz):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter custom size in chat.")

# --- Worker Bulk Message Management (Compatible with Admin Flow) ---
async def handle_worker_bulk_create_all(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker version of create all bulk products."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id): 
        return await query.answer("Access denied.", show_alert=True)
    
    # Reuse the admin bulk execute function but with worker context
    from admin import handle_adm_bulk_execute
    
    # Set worker flag
    context.user_data["is_worker"] = True
    
    try:
        await handle_adm_bulk_execute(update, context, params)
        
        # After completion, update any admin-specific messages to worker context
        # The admin function will handle the actual creation, we just need to adjust the final message
        
    except Exception as e:
        logger.error(f"Error in worker bulk create: {e}")
        await query.answer("❌ Error creating bulk drops. Please try again.", show_alert=True)

async def handle_worker_bulk_remove_last_message(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker version of remove last bulk message."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id): 
        return await query.answer("Access denied.", show_alert=True)
    
    from admin import handle_adm_bulk_remove_last_message
    context.user_data["is_worker"] = True
    await handle_adm_bulk_remove_last_message(update, context, params)

async def handle_worker_bulk_back_to_management(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Worker version of back to bulk management."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_worker(user_id): 
        return await query.answer("Access denied.", show_alert=True)
    
    from admin import show_bulk_messages_status
    context.user_data["is_worker"] = True
    await show_bulk_messages_status(update, context)

# --- Worker Cancel Functions ---
async def handle_worker_cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Cancels the worker add product flow and cleans up."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    # Use same cleanup logic as admin cancel but route back to worker panel
    user_specific_data = context.user_data
    pending_drop = user_specific_data.get("pending_drop")
    
    if pending_drop and "temp_dir" in pending_drop and pending_drop["temp_dir"]:
        temp_dir_path = pending_drop["temp_dir"]
        if await asyncio.to_thread(os.path.exists, temp_dir_path):
            try: 
                await asyncio.to_thread(shutil.rmtree, temp_dir_path, ignore_errors=True)
                logger.info(f"Cleaned temp dir on worker cancel: {temp_dir_path}")
            except Exception as e: 
                logger.error(f"Error cleaning temp dir {temp_dir_path}: {e}")
    
    keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price", "admin_city_id", 
                     "admin_district_id", "admin_product_type", "admin_city", "admin_district", 
                     "collecting_media_group_id", "collected_media", "is_worker"]
    for key in keys_to_clear: 
        user_specific_data.pop(key, None)
    
    if 'collecting_media_group_id' in user_specific_data:
        media_group_id = user_specific_data.pop('collecting_media_group_id', None)
        if media_group_id: 
            # Import here to avoid circular imports
            from admin import remove_job_if_exists
            job_name = f"process_media_group_{user_id}_{media_group_id}"
            remove_job_if_exists(job_name, context)
    
    try:
        await query.edit_message_text("❌ Add Product Cancelled", parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            pass  # It's okay if the message wasn't modified
        else:
            logger.error(f"Error editing cancel message: {e}")
    
    keyboard = [[InlineKeyboardButton("👷 Worker Panel", callback_data="worker_panel")]]
    await send_message_with_retry(context.bot, query.message.chat_id, "Returning to Worker Panel.", 
                                reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_worker_cancel_bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Cancels the worker bulk add flow."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_worker(user_id):
        return await query.answer("Access denied.", show_alert=True)
    
    # Use admin cancel bulk function but adjust routing
    from admin import cancel_bulk_add
    
    # Store original context
    original_context = context.user_data.copy()
    context.user_data["is_worker"] = True
    
    try:
        await cancel_bulk_add(update, context, params)
    except Exception as e:
        logger.error(f"Error in worker cancel bulk: {e}")
    
    # Override the final routing to worker panel
    try:
        keyboard = [[InlineKeyboardButton("👷 Worker Panel", callback_data="worker_panel")]]
        await send_message_with_retry(context.bot, query.message.chat_id, "Bulk operation cancelled. Returning to Worker Panel.", 
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error sending worker cancel bulk message: {e}")

# Export functions that will be used by main.py
__all__ = [
    'handle_worker_panel',
    'handle_worker_city', 'handle_worker_dist', 'handle_worker_type', 'handle_worker_add',
    'handle_worker_size', 'handle_worker_custom_size', 
    'handle_worker_bulk_city', 'handle_worker_bulk_dist', 'handle_worker_bulk_type', 'handle_worker_bulk_add',
    'handle_worker_bulk_size', 'handle_worker_bulk_custom_size', 'handle_worker_bulk_create_all',
    'handle_worker_bulk_remove_last_message', 'handle_worker_bulk_back_to_management',
    'handle_worker_cancel_add', 'handle_worker_cancel_bulk_add', 'handle_close_menu'
] 
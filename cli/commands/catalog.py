import json

import click

from cli.decorators import json_input_options
from cli.helpers import execute_command
from cli.output import OutputFormatter


@click.group()
def catalog():
    """Catalog commands (list, search, find, get-selected, get-info, set-rating, add-keywords, etc.)"""
    pass


@catalog.command("get-selected")
@json_input_options
@click.pass_context
def get_selected(ctx, **kwargs):
    """Get currently selected photos"""
    execute_command(ctx, "catalog.getSelectedPhotos", {})


@catalog.command("list")
@click.option("--limit", default=50, type=int, help="Max photos to return")
@click.option("--offset", default=0, type=int, help="Offset for pagination")
@json_input_options
@click.pass_context
def list_photos(ctx, limit, offset, **kwargs):
    """List photos in catalog"""
    execute_command(ctx, "catalog.getAllPhotos", {"limit": limit, "offset": offset}, timeout=60.0)


@catalog.command("search")
@click.argument("query")
@click.option("--limit", default=50, type=int)
@click.option("--offset", default=0, type=int, help="Result offset for pagination")
@json_input_options
@click.pass_context
def search(ctx, query, limit, offset, **kwargs):
    """Search photos by keyword"""
    # Map the free-text query to the keyword filter (a valid findPhotos key). Sending
    # {"query": ...} hit no known filter and returned the ENTIRE catalog as "results".
    criteria = {"keyword": query}
    execute_command(ctx, "catalog.searchPhotos", {"criteria": criteria, "limit": limit, "offset": offset}, timeout=60.0)


@catalog.command("get-info")
@click.argument("photo_id")
@json_input_options
@click.pass_context
def get_info(ctx, photo_id, **kwargs):
    """Get detailed info for a photo"""
    execute_command(ctx, "catalog.getPhotoMetadata", {"photoId": photo_id})


@catalog.command("set-rating")
@click.argument("photo_id")
@click.argument("rating", type=click.IntRange(0, 5))
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_rating(ctx, photo_id, rating, dry_run, **kwargs):
    """Set photo rating (0-5)"""
    execute_command(ctx, "catalog.setRating", {"photoId": photo_id, "rating": rating})


@catalog.command("add-keywords")
@click.argument("photo_id")
@click.argument("keywords", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def add_keywords(ctx, photo_id, keywords, dry_run, **kwargs):
    """Add keywords to a photo"""
    execute_command(ctx, "catalog.addKeywords", {"photoId": photo_id, "keywords": list(keywords)})


@catalog.command("set-flag")
@click.argument("photo_id")
@click.argument("flag", type=click.Choice(["pick", "reject", "none"]))
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_flag(ctx, photo_id, flag, dry_run, **kwargs):
    """Set photo flag (pick/reject/none)"""
    flag_map = {"pick": 1, "reject": -1, "none": 0}
    execute_command(ctx, "catalog.setFlag", {"photoId": photo_id, "flag": flag_map[flag]})


@catalog.command("batch-set-flag")
@click.option("--photo-ids", required=True, help="Comma-separated photo IDs")
@click.argument("flag", type=click.Choice(["pick", "reject", "none"]))
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def batch_set_flag(ctx, photo_ids, flag, dry_run, **kwargs):
    """Set the same flag (pick/reject/none) on multiple photos in one call"""
    from lightroom_sdk.retry import calculate_batch_timeout

    try:
        ids = [int(pid.strip()) for pid in photo_ids.split(",") if pid.strip()]
    except ValueError:
        fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
        click.echo(
            OutputFormatter.format_error("Invalid photo ID (must be integers)", fmt, code="VALIDATION_ERROR"),
            err=True,
        )
        ctx.exit(2)
        return
    if len(ids) > 50:
        fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
        click.echo(
            OutputFormatter.format_error("Maximum batch size is 50 photos", fmt, code="BATCH_SIZE_EXCEEDED"),
            err=True,
        )
        ctx.exit(2)
        return
    flag_map = {"pick": 1, "reject": -1, "none": 0}
    dynamic_timeout = calculate_batch_timeout(len(ids))
    execute_command(
        ctx,
        "catalog.batchSetFlag",
        {"photoIds": ids, "flag": flag_map[flag]},
        timeout=dynamic_timeout,
    )


def _load_keyword_pairs(path):
    """Read [[photoId, keywordId], ...] or [{"photoId":..,"keywordId":..}, ...] -> list of dicts, or raise ValueError."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("pairs file must hold a non-empty JSON array")
    pairs = []
    for i, p in enumerate(data, 1):
        if isinstance(p, dict):
            pid, kid = p.get("photoId"), p.get("keywordId")
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            pid, kid = p
        else:
            raise ValueError(f"pair {i} must be [photoId, keywordId] or an object with photoId and keywordId")
        if isinstance(pid, bool) or isinstance(kid, bool) or not isinstance(pid, int) or not isinstance(kid, int):
            raise ValueError(f"pair {i}: photoId and keywordId must be integers")
        pairs.append({"photoId": pid, "keywordId": kid})
    return pairs


@catalog.command("batch-remove-keywords")
@click.option(
    "--pairs-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help='JSON file: [[photoId, keywordId], ...] or [{"photoId":..,"keywordId":..}, ...] (max 200 distinct pairs)',
)
@click.option("--catalog-path", default=None, help="Refuse unless Lightroom has this .lrcat open (ids are per-catalog)")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def batch_remove_keywords(ctx, pairs_file, catalog_path, dry_run, **kwargs):
    """Remove keywords (by id) from photos: up to 200 photo/keyword pairs in one write.

    Each pair's status (removed / not_on_photo / photo_not_found / still_present / unverified) comes from reading
    the photo before and after the write; a photo whose keyword count changed by anything else is listed in
    collateralPhotos. Catalog only; the keyword objects stay. Check `complete` in the result.
    """
    _keyword_pairs_command(ctx, pairs_file, catalog_path, kwargs, "catalog.batchRemoveKeywords")


@catalog.command("batch-add-keywords")
@click.option(
    "--pairs-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help='JSON file: [[photoId, keywordId], ...] or [{"photoId":..,"keywordId":..}, ...] (max 200 distinct pairs)',
)
@click.option("--catalog-path", default=None, help="Refuse unless Lightroom has this .lrcat open (ids are per-catalog)")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def batch_add_keywords(ctx, pairs_file, catalog_path, dry_run, **kwargs):
    """Add EXISTING keywords (by id) to photos: up to 200 photo/keyword pairs in one write.

    Never creates a keyword: an id not in the catalog is keyword_not_found (unlike batch-set --keyword, which goes
    by name and creates a missing one). Each pair's status (added / already_on_photo / photo_not_found /
    keyword_not_found / not_added / unverified) comes from reading the photo before and after the write; a photo
    whose keyword count changed by anything else is listed in collateralPhotos. Catalog only. Check `complete`.
    """
    _keyword_pairs_command(ctx, pairs_file, catalog_path, kwargs, "catalog.batchAddKeywords")


@catalog.command("probe-photo")
@click.argument("photo_id")
@json_input_options
@click.pass_context
def probe_photo(ctx, photo_id, **kwargs):
    """DIAGNOSTIC, read-only: run each step of looking a photo up and reading it; report which step fails and how."""
    execute_command(ctx, "catalog.probePhoto", {"photoId": photo_id})


@catalog.command("probe-api")
@click.option("--keyword-id", type=int, default=None, help="Keyword to probe (default: the first top-level keyword)")
@json_input_options
@click.pass_context
def probe_api(ctx, keyword_id, **kwargs):
    """DIAGNOSTIC, read-only: list the methods Lightroom exposes on the catalog and on a keyword; never calls them."""
    params = {} if keyword_id is None else {"keywordId": keyword_id}
    execute_command(ctx, "catalog.probeApi", params)


def _keyword_pairs_command(ctx, pairs_file, catalog_path, kwargs, bridge_command):
    """Shared body of batch-add-keywords / batch-remove-keywords: read and check the pairs, then send them."""
    from lightroom_sdk.retry import calculate_batch_timeout

    fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
    json_given = kwargs.get("json_str") is not None or kwargs.get("json_stdin")
    if pairs_file is None and not json_given:
        click.echo(
            OutputFormatter.format_error("--pairs-file (or --json / --json-stdin) is required", fmt,
                                         code="VALIDATION_ERROR"),
            err=True,
        )
        ctx.exit(2)
        return
    pairs = []
    if pairs_file is not None:
        try:
            pairs = _load_keyword_pairs(pairs_file)
        except (ValueError, OSError) as e:
            click.echo(OutputFormatter.format_error(str(e), fmt, code="VALIDATION_ERROR"), err=True)
            ctx.exit(2)
            return
        distinct = {(p["photoId"], p["keywordId"]) for p in pairs}
        if len(distinct) > 200:
            click.echo(
                OutputFormatter.format_error("Maximum batch size is 200 pairs", fmt, code="BATCH_SIZE_EXCEEDED"),
                err=True,
            )
            ctx.exit(2)
            return
    # The plugin side allows up to 110 s (CommandRouter); --json input may carry a full 200 pairs, so use the cap.
    params = {"pairs": pairs}
    if catalog_path:
        params["catalogPath"] = catalog_path
    execute_command(ctx, bridge_command, params, timeout=calculate_batch_timeout(200))


@catalog.command("get-flag")
@click.argument("photo_id")
@json_input_options
@click.pass_context
def get_flag(ctx, photo_id, **kwargs):
    """Get photo flag status"""
    execute_command(ctx, "catalog.getFlag", {"photoId": photo_id})


@catalog.command("find")
@click.option("--flag", type=click.Choice(["pick", "reject", "none"]), help="Flag condition")
@click.option("--rating", type=int, help="Rating (0-5)")
@click.option(
    "--rating-op",
    default="==",
    type=click.Choice(["==", ">=", "<=", ">", "<"]),
    help="Rating comparison operator",
)
@click.option("--color-label", help="Color label (red/yellow/green/blue/purple/none)")
@click.option("--camera", help="Camera model name")
@click.option("--folder-path", help="Folder path (substring match)")
@click.option("--capture-date-from", help="Capture date from (YYYY-MM-DD or ISO 8601)")
@click.option("--capture-date-to", help="Capture date to (YYYY-MM-DD or ISO 8601, inclusive)")
@click.option("--file-format", help="File format (RAW/DNG/JPEG)")
@click.option("--keyword", "keyword_filter", help="Keyword (substring match)")
@click.option("--filename", help="Filename (substring match)")
@click.option("--text", help="Free-text (substring across filename, title, caption)")
@click.option("--limit", default=50, type=int, help="Max results")
@click.option("--offset", default=0, type=int, help="Offset for pagination")
@json_input_options
@click.pass_context
def find_photos(
    ctx,
    flag,
    rating,
    rating_op,
    color_label,
    camera,
    folder_path,
    capture_date_from,
    capture_date_to,
    file_format,
    keyword_filter,
    filename,
    text,
    limit,
    offset,
    **kwargs,
):
    """Find photos by structured criteria"""
    search_desc = {}
    if flag:
        search_desc["flag"] = flag
    if rating is not None:
        search_desc["rating"] = rating
        search_desc["ratingOp"] = rating_op
    if color_label:
        search_desc["colorLabel"] = color_label
    if camera:
        search_desc["camera"] = camera
    if folder_path:
        search_desc["folderPath"] = folder_path
    if capture_date_from:
        search_desc["captureDateFrom"] = capture_date_from
    if capture_date_to:
        search_desc["captureDateTo"] = capture_date_to
    if file_format:
        search_desc["fileFormat"] = file_format
    if keyword_filter:
        search_desc["keyword"] = keyword_filter
    if filename:
        search_desc["filename"] = filename
    if text:
        search_desc["text"] = text

    execute_command(
        ctx,
        "catalog.findPhotos",
        {"searchDesc": search_desc, "limit": limit, "offset": offset},
        timeout=90.0,
    )


@catalog.command("select")
@click.argument("photo_ids", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def select_photos(ctx, photo_ids, dry_run, **kwargs):
    """Select photos by ID"""
    execute_command(ctx, "catalog.setSelectedPhotos", {"photoIds": list(photo_ids)})


@catalog.command("find-by-path")
@click.argument("path")
@json_input_options
@click.pass_context
def find_by_path(ctx, path, **kwargs):
    """Find photo by file path"""
    execute_command(ctx, "catalog.findPhotoByPath", {"path": path})


@catalog.command("collections")
@json_input_options
@click.pass_context
def collections(ctx, **kwargs):
    """List collections in catalog"""
    execute_command(ctx, "catalog.getCollections", {})


@catalog.command("collection-photos")
@click.argument("collection_id", type=int)
@click.option("--limit", default=500, type=int, help="Max photos to return")
@click.option("--offset", default=0, type=int, help="Offset for pagination")
@json_input_options
@click.pass_context
def collection_photos(ctx, collection_id, limit, offset, **kwargs):
    """Get photos from a specific collection"""
    execute_command(
        ctx,
        "catalog.getCollectionPhotos",
        {"collectionId": collection_id, "limit": limit, "offset": offset},
        timeout=60.0,
    )


@catalog.command("develop-presets")
@click.option("--query", default=None, help="Search query to filter presets by name")
@json_input_options
@click.pass_context
def develop_presets(ctx, query, **kwargs):
    """List or search develop presets"""
    params = {}
    if query:
        params["query"] = query
    execute_command(ctx, "catalog.getDevelopPresets", params)


@catalog.command("keywords")
@json_input_options
@click.pass_context
def keywords(ctx, **kwargs):
    """List keywords in catalog"""
    execute_command(ctx, "catalog.getKeywords", {})


@catalog.command("folders")
@click.option("--recursive", is_flag=True, help="Include subfolders")
@json_input_options
@click.pass_context
def folders(ctx, recursive, **kwargs):
    """List folders in catalog"""
    execute_command(ctx, "catalog.getFolders", {"includeSubfolders": recursive})


@catalog.command("set-title")
@click.argument("photo_id")
@click.argument("title")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_title(ctx, photo_id, title, dry_run, **kwargs):
    """Set photo title"""
    execute_command(ctx, "catalog.setTitle", {"photoId": photo_id, "title": title})


@catalog.command("set-caption")
@click.argument("photo_id")
@click.argument("caption")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_caption(ctx, photo_id, caption, dry_run, **kwargs):
    """Set photo caption"""
    execute_command(ctx, "catalog.setCaption", {"photoId": photo_id, "caption": caption})


@catalog.command("set-color-label")
@click.argument("photo_id")
@click.argument("label", type=click.Choice(["red", "yellow", "green", "blue", "purple", "none"]))
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_color_label(ctx, photo_id, label, dry_run, **kwargs):
    """Set photo color label"""
    execute_command(ctx, "catalog.setColorLabel", {"photoId": photo_id, "label": label})


@catalog.command("batch-metadata")
@click.argument("photo_ids", nargs=-1, required=True)
@click.option(
    "--keys",
    default="fileName,dateTimeOriginal,rating",
    help="Comma-separated metadata keys",
)
@json_input_options
@click.pass_context
def batch_metadata(ctx, photo_ids, keys, **kwargs):
    """Get formatted metadata for multiple photos"""
    execute_command(
        ctx,
        "catalog.batchGetFormattedMetadata",
        {"photoIds": list(photo_ids), "keys": keys.split(",")},
    )


@catalog.command("rotate-left")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def rotate_left(ctx, dry_run, **kwargs):
    """Rotate selected photo left"""
    execute_command(ctx, "catalog.rotateLeft", {})


@catalog.command("rotate-right")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def rotate_right(ctx, dry_run, **kwargs):
    """Rotate selected photo right"""
    execute_command(ctx, "catalog.rotateRight", {})


@catalog.command("create-virtual-copy")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def create_virtual_copy(ctx, dry_run, **kwargs):
    """Create virtual copy of selected photo"""
    execute_command(ctx, "catalog.createVirtualCopy", {})


@catalog.command("set-metadata")
@click.argument("photo_id")
@click.argument("key")
@click.argument("value")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_metadata(ctx, photo_id, key, value, dry_run, **kwargs):
    """Set arbitrary metadata key/value for a photo"""
    from cli.helpers import coerce_scalar

    execute_command(ctx, "catalog.setMetadata", {"photoId": photo_id, "key": key, "value": coerce_scalar(value)})


@catalog.command("create-collection")
@click.argument("name")
@click.option("--parent", type=int, default=None, help="Parent collection-set ID to nest the new collection under")
@click.option(
    "--return-existing/--no-return-existing",
    default=True,
    help="Return the existing collection if one with this name already exists",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def create_collection(ctx, name, parent, return_existing, dry_run, **kwargs):
    """Create a new collection (returns the new collection id)"""
    params = {"name": name, "returnExisting": return_existing}
    if parent is not None:
        params["parentId"] = parent
    execute_command(ctx, "catalog.createCollection", params)


@catalog.command("add-to-collection")
@click.argument("collection_id", type=int)
@click.argument("photo_ids", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def add_to_collection(ctx, collection_id, photo_ids, dry_run, **kwargs):
    """Add photos to a collection by ID"""
    execute_command(
        ctx,
        "catalog.addPhotosToCollection",
        {"collectionId": collection_id, "photoIds": list(photo_ids)},
        timeout=60.0,
    )


@catalog.command("remove-from-collection")
@click.argument("collection_id", type=int)
@click.argument("photo_ids", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def remove_from_collection(ctx, collection_id, photo_ids, dry_run, **kwargs):
    """Remove photos from a collection by ID (does not delete the photos)"""
    execute_command(
        ctx,
        "catalog.removePhotosFromCollection",
        {"collectionId": collection_id, "photoIds": list(photo_ids)},
        timeout=60.0,
    )


@catalog.command("batch-set")
@click.argument("photo_ids", nargs=-1, required=False)
@click.option("--rating", type=int, default=None, help="Rating 0-5 (0 clears)")
@click.option("--color-label", default=None, help="Color label (red/yellow/green/blue/purple/none)")
@click.option("--flag", type=click.Choice(["pick", "reject", "none"]), default=None, help="Pick flag")
@click.option("--title", default=None, help="Title, applied to every photo")
@click.option("--caption", default=None, help="Caption, applied to every photo")
@click.option("--keyword", "keywords", multiple=True, help="Keyword to add to every photo (repeatable)")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def batch_set(ctx, photo_ids, rating, color_label, flag, title, caption, keywords, dry_run, **kwargs):
    """Set metadata fields across many photos at once (current selection if no IDs are given)."""
    params = {}
    if photo_ids:
        params["photoIds"] = list(photo_ids)
    if rating is not None:
        params["rating"] = rating
    if color_label:
        params["colorLabel"] = color_label
    if flag:
        params["flag"] = {"pick": 1, "reject": -1, "none": 0}[flag]
    if title is not None:
        params["title"] = title
    if caption is not None:
        params["caption"] = caption
    if keywords:
        params["addKeywords"] = list(keywords)
    execute_command(ctx, "catalog.batchSetMetadata", params, timeout=60.0)


@catalog.command("save-metadata")
@click.argument("photo_ids", nargs=-1, required=False)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def save_metadata(ctx, photo_ids, dry_run, **kwargs):
    """Save catalog metadata to each photo's file XMP (current selection if no IDs are given)."""
    params = {}
    if photo_ids:
        params["photoIds"] = list(photo_ids)
    execute_command(ctx, "catalog.saveMetadata", params, timeout=120.0)


@catalog.command("import")
@click.argument("paths", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def import_photos(ctx, paths, dry_run, **kwargs):
    """Add existing files to the catalog (referenced in place): lr catalog import <path>..."""
    execute_command(ctx, "catalog.importPhotos", {"paths": list(paths)}, timeout=120.0)


@catalog.command("create-smart-collection")
@click.argument("name")
@click.option("--search-desc", default=None, help="JSON search descriptor")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def create_smart_collection(ctx, name, search_desc, dry_run, **kwargs):
    """Create a smart collection"""
    params = {"name": name}
    if search_desc:
        try:
            params["searchDesc"] = json.loads(search_desc)
        except json.JSONDecodeError as e:
            fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
            click.echo(OutputFormatter.format_error(f"Invalid JSON for --search-desc: {e}", fmt, code="VALIDATION_ERROR"))
            ctx.exit(1)
            return
    execute_command(ctx, "catalog.createSmartCollection", params)


@catalog.command("create-collection-set")
@click.argument("name")
@click.option("--parent", type=int, default=None, help="Parent collection-set ID to nest this set under")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def create_collection_set(ctx, name, parent, dry_run, **kwargs):
    """Create a collection set"""
    params = {"name": name}
    if parent is not None:
        params["parentId"] = parent
    execute_command(ctx, "catalog.createCollectionSet", params)


@catalog.command("rename-collection")
@click.argument("collection_id", type=int)
@click.argument("new_name")
@json_input_options
@click.pass_context
def rename_collection(ctx, collection_id, new_name, **kwargs):
    """Rename an existing collection by id"""
    execute_command(ctx, "catalog.renameCollection", {"collectionId": collection_id, "newName": new_name})


@catalog.command("delete-collection")
@click.argument("collection_id", type=int)
@json_input_options
@click.pass_context
def delete_collection(ctx, collection_id, **kwargs):
    """Delete a collection or collection set by id (does not touch member photos)"""
    execute_command(ctx, "catalog.deleteCollection", {"collectionId": collection_id})


@catalog.command("create-keyword")
@click.argument("keyword")
@click.option("--parent-id", type=int, default=None, help="Create it inside the keyword with this id")
@click.option("--parent", "parent_name", default=None,
              help="Create it inside the keyword with this exact name (must name exactly one keyword)")
@click.option("--no-export", is_flag=True, default=False, help="Create it with 'Include on Export' unchecked")
@click.option("--catalog-path", default=None, help="Refuse unless Lightroom has this .lrcat open")
@click.option("--allow-duplicate-name", is_flag=True, default=False,
              help="Create it even if a keyword with the same name (any capitals) exists elsewhere in the tree")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def create_keyword(ctx, keyword, parent_id, parent_name, no_export, catalog_path, allow_duplicate_name, dry_run,
                   **kwargs):
    """Create a keyword, optionally inside an existing parent keyword.

    Give --parent-id or --parent: without one, Lightroom puts the keyword under whatever keyword was last selected in
    its Keyword List, not at the top level (the response says where it landed). Refuses if the name already exists
    elsewhere; returns the existing keyword (created=false) if it is already where you asked. Reads back the
    placement: a keyword that landed outside the requested parent is PLACEMENT_MISMATCH.
    """
    params = {"keyword": keyword}
    if parent_id is not None:
        params["parentId"] = parent_id
    if parent_name is not None:
        params["parent"] = parent_name
    if no_export:
        params["includeOnExport"] = False
    if catalog_path:
        params["catalogPath"] = catalog_path
    if allow_duplicate_name:
        params["allowDuplicateName"] = True
    execute_command(ctx, "catalog.createKeyword", params)


@catalog.command("move-keyword")
@click.argument("keyword_id", type=int)
@click.option("--parent-id", type=int, default=None, help="Move it inside the keyword with this id")
@click.option("--parent", "parent_name", default=None,
              help="Move it inside the keyword with this exact name (must name exactly one keyword)")
@click.option("--to-top", is_flag=True, default=False, help="Move it to the top level of the Keyword List")
@click.option("--catalog-path", default=None, help="Refuse unless Lightroom has this .lrcat open")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def move_keyword(ctx, keyword_id, parent_id, parent_name, to_top, catalog_path, dry_run, **kwargs):
    """Move a keyword inside another keyword, or to the top level; it keeps its id, photos and children.

    Give exactly one of --parent-id, --parent or --to-top. Afterwards the keyword is re-read by id: it must sit
    directly in the target with the same photo and child counts, else an error says where it is and what changed.
    Refuses a target inside the keyword itself, or one already holding a keyword of the same name (any capitals).
    Already there: moved=false, nothing written. Catalog only.
    """
    params = {"keywordId": keyword_id}
    if parent_id is not None:
        params["parentId"] = parent_id
    if parent_name is not None:
        params["parent"] = parent_name
    if to_top:
        params["toTop"] = True
    if catalog_path:
        params["catalogPath"] = catalog_path
    execute_command(ctx, "catalog.moveKeyword", params)


@catalog.command("remove-keyword")
@click.argument("photo_id")
@click.argument("keyword")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def remove_keyword(ctx, photo_id, keyword, dry_run, **kwargs):
    """Remove keyword from a photo"""
    execute_command(ctx, "catalog.removeKeyword", {"photoId": photo_id, "keyword": keyword})


@catalog.command("rename-keyword")
@click.argument("keyword_id")
@click.argument("new_name")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def rename_keyword(ctx, keyword_id, new_name, dry_run, **kwargs):
    """Rename a keyword by id (keeps its photos, faces, and synonyms; catalog only -- Save Metadata writes files)"""
    execute_command(ctx, "catalog.renameKeyword", {"keywordId": keyword_id, "newName": new_name})


@catalog.command("set-view-filter")
@click.option("--filter", "filter_json", required=True, help="JSON filter descriptor")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def set_view_filter(ctx, filter_json, dry_run, **kwargs):
    """Set view filter"""
    try:
        filter_data = json.loads(filter_json)
    except json.JSONDecodeError as e:
        fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
        click.echo(OutputFormatter.format_error(f"Invalid JSON for --filter: {e}", fmt, code="VALIDATION_ERROR"))
        ctx.exit(1)
        return
    execute_command(ctx, "catalog.setViewFilter", {"filter": filter_data})


@catalog.command("get-view-filter")
@json_input_options
@click.pass_context
def get_view_filter(ctx, **kwargs):
    """Get current view filter"""
    execute_command(ctx, "catalog.getCurrentViewFilter", {})


@catalog.command("remove-from-catalog")
@click.argument("photo_id")
@click.option(
    "--confirm",
    is_flag=True,
    default=False,
    help="Required confirmation flag (this operation is irreversible)",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing")
@json_input_options
@click.pass_context
def remove_from_catalog(ctx, photo_id, confirm, dry_run, **kwargs):
    """Remove photo from catalog (irreversible, requires --confirm)"""
    if not confirm and not dry_run:
        fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
        click.echo(
            OutputFormatter.format_error(
                "This operation is irreversible. Pass --confirm to proceed.",
                fmt,
                code="CONFIRMATION_REQUIRED",
                suggestions=[
                    "Add --confirm flag: lr catalog remove-from-catalog PHOTO_ID --confirm",
                    "Use --dry-run first to preview: lr catalog remove-from-catalog PHOTO_ID --dry-run",
                ],
            ),
            err=True,
        )
        ctx.exit(2)
        return
    execute_command(ctx, "catalog.removeFromCatalog", {"photoId": photo_id})

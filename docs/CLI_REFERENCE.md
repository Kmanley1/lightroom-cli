# lr CLI Reference

> Generated from `lightroom_sdk/schema.py` via `lr docs reference`. Do not edit by hand --
> regenerate after any schema change.

**135 commands** across 7 groups. Every command is reachable both as a CLI verb and as an MCP tool.

## Groups

- [`catalog`](#catalog) -- 36 commands
- [`develop`](#develop) -- 65 commands
- [`export`](#export) -- 1 commands
- [`plugin`](#plugin) -- 3 commands
- [`preview`](#preview) -- 3 commands
- [`selection`](#selection) -- 23 commands
- [`system`](#system) -- 4 commands

## catalog

### `lr catalog add-keywords`

Add keywords to a photo

**MCP tool:** `lr_catalog_add_keywords`  -  **bridge:** `catalog.addKeywords`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `keywords` | json_array | yes |  | Array of keyword strings to add |

**Response fields:** `photoId`, `keywords`

### `lr catalog add-to-collection`

Add photos to a collection by ID

**MCP tool:** `lr_catalog_add_photos_to_collection`  -  **bridge:** `catalog.addPhotosToCollection`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `collectionId` | integer | yes |  | Target collection ID (from catalog collections) |
| `photoIds` | json_array | yes |  | Photo ID strings to add |

**Response fields:** `collectionId`, `collectionName`, `photoCount`, `affected`, `requested`, `notFound`

### `lr catalog batch-metadata`

Get formatted metadata for multiple photos

**MCP tool:** `lr_catalog_batch_get_formatted_metadata`  -  **bridge:** `catalog.batchGetFormattedMetadata`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array | yes |  | Array of photo ID strings |
| `keys` | json_array | yes |  | Array of metadata key names to retrieve |

**Response fields:** `photos`, `keys`

### `lr catalog batch-set`

Set metadata fields (rating/colorLabel/flag/title/caption/keywords) across many photos in one transaction

**MCP tool:** `lr_catalog_batch_set_metadata`  -  **bridge:** `catalog.batchSetMetadata`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array |  |  | Photo IDs; omit to use the current selection |
| `rating` | integer |  |  | Rating 0-5 (0 clears) [min 0, max 5] |
| `colorLabel` | string |  |  | Color label (red/yellow/green/blue/purple/none) |
| `flag` | integer |  |  | Pick flag: 1 pick, -1 reject, 0 none [min -1, max 1] |
| `title` | string |  |  | Title, applied to every photo |
| `caption` | string |  |  | Caption, applied to every photo |
| `addKeywords` | json_array |  |  | Keyword names to add to every photo |

**Response fields:** `total`, `succeeded`, `failed`, `results`

### `lr catalog collection-photos`

Get photos from a specific collection

**MCP tool:** `lr_catalog_get_collection_photos`  -  **bridge:** `catalog.getCollectionPhotos`  -  **risk:** read  -  **timeout:** 60s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `collectionId` | integer | yes |  | Collection ID (obtain via catalog collections) |
| `limit` | integer |  | `500` | Max photos to return |
| `offset` | integer |  | `0` | Offset for pagination [min 0] |

**Response fields:** `photos`, `total`, `returned`, `collectionName`

### `lr catalog collections`

List collections in catalog

**MCP tool:** `lr_catalog_get_collections`  -  **bridge:** `catalog.getCollections`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `collections`

### `lr catalog create-collection`

Create a new collection (returns the new collection id)

**MCP tool:** `lr_catalog_create_collection`  -  **bridge:** `catalog.createCollection`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes |  | Collection name |
| `parentId` | integer |  |  | Parent collection-set id to nest under (top-level if omitted) |
| `returnExisting` | boolean |  | `True` | Return the existing collection if one with this name already exists |

**Response fields:** `id`, `name`

### `lr catalog create-collection-set`

Create a collection set

**MCP tool:** `lr_catalog_create_collection_set`  -  **bridge:** `catalog.createCollectionSet`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes |  | Collection set name |

### `lr catalog create-keyword`

Create a keyword in catalog

**MCP tool:** `lr_catalog_create_keyword`  -  **bridge:** `catalog.createKeyword`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `keyword` | string | yes |  | Keyword string to create |

### `lr catalog create-smart-collection`

Create a smart collection

**MCP tool:** `lr_catalog_create_smart_collection`  -  **bridge:** `catalog.createSmartCollection`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes |  | Smart collection name |
| `searchDesc` | json_object |  |  | Search criteria as JSON object |

### `lr catalog create-virtual-copy`

Create virtual copy of selected photo

**MCP tool:** `lr_catalog_create_virtual_copy`  -  **bridge:** `catalog.createVirtualCopy`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr catalog develop-presets`

List or search develop presets

**MCP tool:** `lr_catalog_get_develop_presets`  -  **bridge:** `catalog.getDevelopPresets`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | string |  |  | Search query to filter presets by name (case-insensitive) |

**Response fields:** `presets`, `count`

### `lr catalog find`

Find photos by structured criteria

**MCP tool:** `lr_catalog_find_photos`  -  **bridge:** `catalog.findPhotos`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `searchDesc` | json_object | yes |  | Search criteria as JSON object |
| `limit` | integer |  | `50` | Maximum number of results to return |
| `offset` | integer |  | `0` | Number of results to skip for pagination |

**Response fields:** `photos`, `total`, `criteria`

### `lr catalog find-by-path`

Find photo by file path

**MCP tool:** `lr_catalog_find_photo_by_path`  -  **bridge:** `catalog.findPhotoByPath`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `path` | string | yes |  | Absolute file path of the photo |

**Response fields:** `photo`, `found`

### `lr catalog folders`

List folders in catalog

**MCP tool:** `lr_catalog_get_folders`  -  **bridge:** `catalog.getFolders`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `includeSubfolders` | boolean |  | `False` | Include subfolders in the listing |

**Response fields:** `folders`

### `lr catalog get-flag`

Get photo flag status

**MCP tool:** `lr_catalog_get_flag`  -  **bridge:** `catalog.getFlag`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |

**Response fields:** `photoId`, `flag`

### `lr catalog get-info`

Get detailed info for a photo

**MCP tool:** `lr_catalog_get_photo_metadata`  -  **bridge:** `catalog.getPhotoMetadata`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |

**Response fields:** `filename`, `path`, `rating`, `flag`, `keywords`, `dimensions`, `dateCreated`

### `lr catalog get-selected`

Get currently selected photos

**MCP tool:** `lr_catalog_get_selected_photos`  -  **bridge:** `catalog.getSelectedPhotos`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `photos`, `count`

### `lr catalog get-view-filter`

Get current view filter

**MCP tool:** `lr_catalog_get_current_view_filter`  -  **bridge:** `catalog.getCurrentViewFilter`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `filter`

### `lr catalog keywords`

List keywords in catalog

**MCP tool:** `lr_catalog_get_keywords`  -  **bridge:** `catalog.getKeywords`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `keywords`

### `lr catalog list`

List photos in catalog

**MCP tool:** `lr_catalog_get_all_photos`  -  **bridge:** `catalog.getAllPhotos`  -  **risk:** read  -  **timeout:** 60s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `limit` | integer |  | `50` | Maximum number of results to return |
| `offset` | integer |  | `0` | Number of results to skip for pagination |

**Response fields:** `photos`, `total`, `limit`, `offset`

### `lr catalog remove-from-catalog`

Remove photo from catalog

**MCP tool:** `lr_catalog_remove_from_catalog`  -  **bridge:** `catalog.removeFromCatalog`  -  **risk:** destructive  -  **timeout:** 30s  -  dry-run  -  **requires --confirm**

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID to remove from catalog |

### `lr catalog remove-from-collection`

Remove photos from a collection by ID (does not delete the photos)

**MCP tool:** `lr_catalog_remove_photos_from_collection`  -  **bridge:** `catalog.removePhotosFromCollection`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `collectionId` | integer | yes |  | Target collection ID |
| `photoIds` | json_array | yes |  | Photo ID strings to remove |

**Response fields:** `collectionId`, `collectionName`, `photoCount`, `affected`, `requested`, `notFound`

### `lr catalog remove-keyword`

Remove keyword from a photo

**MCP tool:** `lr_catalog_remove_keyword`  -  **bridge:** `catalog.removeKeyword`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `keyword` | string | yes |  | Keyword string to remove |

### `lr catalog rotate-left`

Rotate selected photo left

**MCP tool:** `lr_catalog_rotate_left`  -  **bridge:** `catalog.rotateLeft`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr catalog rotate-right`

Rotate selected photo right

**MCP tool:** `lr_catalog_rotate_right`  -  **bridge:** `catalog.rotateRight`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr catalog save-metadata`

Write catalog metadata to each photo's file XMP (by ID or current selection). Read-from-file is intentionally not exposed -- it would overwrite catalog edits.

**MCP tool:** `lr_catalog_save_metadata`  -  **bridge:** `catalog.saveMetadata`  -  **risk:** write  -  **timeout:** 120s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array |  |  | Photo IDs; omit to use the current selection |

**Response fields:** `total`, `succeeded`, `failed`, `results`

### `lr catalog search`

Search photos by criteria

**MCP tool:** `lr_catalog_search_photos`  -  **bridge:** `catalog.searchPhotos`  -  **risk:** read  -  **timeout:** 60s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `criteria` | json_object |  |  | Search criteria object |
| `limit` | integer |  | `100` | Maximum number of results (1-10000, default: 100) |
| `offset` | integer |  | `0` | Result offset (default: 0) |

**Response fields:** `photos`, `total`, `query`

### `lr catalog select`

Select photos by ID

**MCP tool:** `lr_catalog_set_selected_photos`  -  **bridge:** `catalog.setSelectedPhotos`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array | yes |  | Array of photo ID strings to select |

### `lr catalog set-caption`

Set photo caption

**MCP tool:** `lr_catalog_set_caption`  -  **bridge:** `catalog.setCaption`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `caption` | string | yes |  | Caption text to set |

### `lr catalog set-color-label`

Set photo color label

**MCP tool:** `lr_catalog_set_color_label`  -  **bridge:** `catalog.setColorLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `label` | enum | yes |  | Color label to set (one of: red, yellow, green, blue, purple, none) |

### `lr catalog set-flag`

Set photo flag (pick/reject/none)

**MCP tool:** `lr_catalog_set_flag`  -  **bridge:** `catalog.setFlag`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `flag` | integer | yes |  | Flag value (1=pick, -1=reject, 0=none) |

**Response fields:** `photoId`, `flag`

### `lr catalog set-metadata`

Set arbitrary metadata key/value

**MCP tool:** `lr_catalog_set_metadata`  -  **bridge:** `catalog.setMetadata`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `key` | string | yes |  | Metadata key name |
| `value` | scalar | yes |  | Metadata value to set (number, boolean, or string per the key) |

### `lr catalog set-rating`

Set photo star rating

**MCP tool:** `lr_catalog_set_rating`  -  **bridge:** `catalog.setRating`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `rating` | integer | yes |  | Star rating (0-5) [min 0, max 5] |

**Response fields:** `photoId`, `rating`

### `lr catalog set-title`

Set photo title

**MCP tool:** `lr_catalog_set_title`  -  **bridge:** `catalog.setTitle`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID (obtain via catalog list or get-selected) |
| `title` | string | yes |  | Title text to set |

### `lr catalog set-view-filter`

Set view filter

**MCP tool:** `lr_catalog_set_view_filter`  -  **bridge:** `catalog.setViewFilter`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `filter` | json_object | yes |  | View filter criteria as JSON object |

## develop

### `lr develop ai _bridge`

Create AI mask with adjustments (internal bridge command)

**MCP tool:** `lr_develop_create_ai_mask_with_adjustments`  -  **bridge:** `develop.createAIMaskWithAdjustments`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `selectionType` | enum | yes |  | AI mask selection type (one of: subject, sky, background, objects, people, landscape) |
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |
| `part` | string |  |  | Specific part to mask |

### `lr develop ai background`

Create AI background mask with optional adjustments

**MCP tool:** `lr_develop_ai_background`  -  **bridge:** `develop.ai.background`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop ai batch`

Apply AI mask to multiple photos

**MCP tool:** `lr_develop_batch_ai_mask`  -  **bridge:** `develop.batchAIMask`  -  **risk:** write  -  **timeout:** 300s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `selectionType` | enum | yes |  | AI mask selection type (one of: subject, sky, background, objects, people, landscape) |
| `photoIds` | json_array |  |  | Array of photo ID strings to process |
| `allSelected` | boolean |  | `False` | Apply to all currently selected photos |
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |
| `continueOnError` | boolean |  | `False` | Continue processing if a photo fails |
| `part` | string |  |  | Specific part to mask (e.g. eyes, hair, mountain) |

### `lr develop ai landscape`

Create AI landscape mask with optional adjustments

**MCP tool:** `lr_develop_ai_landscape`  -  **bridge:** `develop.ai.landscape`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `part` | string |  |  | Specific part to mask (e.g. mountain, tree) |
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop ai list`

List all masks on the current photo

**MCP tool:** `lr_develop_ai_list`  -  **bridge:** `develop.ai.list`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `masks`, `count`

### `lr develop ai objects`

Create AI objects mask with optional adjustments

**MCP tool:** `lr_develop_ai_objects`  -  **bridge:** `develop.ai.objects`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop ai people`

Create AI people mask with optional adjustments

**MCP tool:** `lr_develop_ai_people`  -  **bridge:** `develop.ai.people`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `part` | string |  |  | Specific part to mask (e.g. eyes, hair) |
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop ai presets`

List available adjustment presets

**MCP tool:** `lr_develop_ai_presets`  -  **bridge:** `develop.ai.presets`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `presets`

### `lr develop ai reset`

Remove all masks from the current photo

**MCP tool:** `lr_develop_ai_reset`  -  **bridge:** `develop.ai.reset`  -  **risk:** destructive  -  **timeout:** 30s  -  dry-run  -  **requires --confirm**

_No parameters._

### `lr develop ai sky`

Create AI sky mask with optional adjustments

**MCP tool:** `lr_develop_ai_sky`  -  **bridge:** `develop.ai.sky`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop ai subject`

Create AI subject mask with optional adjustments

**MCP tool:** `lr_develop_ai_subject`  -  **bridge:** `develop.ai.subject`  -  **risk:** write  -  **timeout:** 60s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `adjustments` | json_object |  |  | Optional develop adjustments to apply |

### `lr develop apply`

Apply develop settings to a specific photo

**MCP tool:** `lr_develop_apply_settings`  -  **bridge:** `develop.applySettings`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string |  |  | Target photo ID (required by Lightroom — use catalog.getSelected to obtain) |
| `settings` | json_object | yes |  | JSON object of settings to apply (e.g., {"Exposure": 0.5, "Contrast": 20}) |

**Response fields:** `applied`, `settings`

### `lr develop auto-tone`

Apply auto tone adjustments

**MCP tool:** `lr_develop_set_auto_tone`  -  **bridge:** `develop.setAutoTone`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

**Response fields:** `status`

### `lr develop auto-wb`

Apply auto white balance

**MCP tool:** `lr_develop_set_auto_white_balance`  -  **bridge:** `develop.setAutoWhiteBalance`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

**Response fields:** `status`

### `lr develop batch-apply`

Batch apply develop settings to multiple photos

**MCP tool:** `lr_develop_batch_apply_settings`  -  **bridge:** `develop.batchApplySettings`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array |  |  | Array of photo IDs to apply settings to (required by Lightroom) |
| `settings` | json_object | yes |  | JSON object of settings to apply (e.g., {"Exposure": 0.5, "Contrast": 20}) |

**Response fields:** `applied`, `settings`

### `lr develop batch-set`

Batch set a single develop parameter across multiple photos

**MCP tool:** `lr_develop_batch_set_value`  -  **bridge:** `develop.batchSetValue`  -  **risk:** write  -  **timeout:** 120s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array | yes |  | Array of photo IDs |
| `param` | string | yes |  | Develop parameter name (e.g., Exposure, Contrast) |
| `value` | float | yes |  | Value to set |

**Response fields:** `results`, `successCount`, `failCount`

### `lr develop color cyan-swatch`

Create cyan color swatch

**MCP tool:** `lr_develop_create_cyan_swatch`  -  **bridge:** `develop.createCyanSwatch`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `saturationBoost` | float |  |  | Saturation scale value (default: 0.2) |
| `luminanceAdjust` | float |  |  | Luminance scale value (default: 0) |
| `hueShift` | float |  |  | Hue shift amount (default: 0) |
| `rangeWidth` | string |  |  | Range width: tight, normal, wide (default: normal) |

### `lr develop color enhance`

Enhance colors

**MCP tool:** `lr_develop_enhance_colors`  -  **bridge:** `develop.enhanceColors`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `preset` | enum |  |  | Color enhancement preset (one of: natural, vivid, muted) |
| `preserveExisting` | boolean |  |  | Merge with existing PointColors (default: false) |

### `lr develop color green-swatch`

Create green color swatch

**MCP tool:** `lr_develop_create_green_swatch`  -  **bridge:** `develop.createGreenSwatch`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `saturationBoost` | float |  |  | Saturation scale value (default: 0) |
| `luminanceAdjust` | float |  |  | Luminance scale value (default: 0) |
| `hueShift` | float |  |  | Hue shift amount (default: -0.1) |
| `rangeWidth` | string |  |  | Range width: tight, normal, wide (default: normal) |

### `lr develop copy-settings`

Copy develop settings from selected photo

**MCP tool:** `lr_catalog_copy_settings`  -  **bridge:** `catalog.copySettings`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `status`

### `lr develop curve add-point`

Add a point to the tone curve

**MCP tool:** `lr_develop_add_curve_point`  -  **bridge:** `develop.addCurvePoint`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name |
| `x` | float | yes |  | X coordinate (input value, 0-255) |
| `y` | float | yes |  | Y coordinate (output value, 0-255) |

### `lr develop curve get`

Get tone curve points

**MCP tool:** `lr_develop_get_curve_points`  -  **bridge:** `develop.getCurvePoints`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name |

**Response fields:** `points`, `param`

### `lr develop curve linear`

Reset curve to linear

**MCP tool:** `lr_develop_set_curve_linear`  -  **bridge:** `develop.setCurveLinear`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name |

### `lr develop curve remove-point`

Remove a point from the tone curve

**MCP tool:** `lr_develop_remove_curve_point`  -  **bridge:** `develop.removeCurvePoint`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name |
| `index` | integer | yes |  | Zero-based index of the point to remove |

### `lr develop curve s-curve`

Apply S-curve preset

**MCP tool:** `lr_develop_set_curve_s_curve`  -  **bridge:** `develop.setCurveSCurve`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name |
| `strength` | integer |  |  | S-curve strength 0-100 (default: 25) |

### `lr develop curve set`

Set tone curve points

**MCP tool:** `lr_develop_set_curve_points`  -  **bridge:** `develop.setCurvePoints`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Curve parameter name (e.g., ParametricDarks) |
| `points` | json_array | yes |  | Array of {x, y} control points, each 0-255 |

### `lr develop debug dump`

Dump LrDevelopController info

**MCP tool:** `lr_develop_dump_lr_develop_controller`  -  **bridge:** `develop.dumpLrDevelopController`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

### `lr develop debug gradient-params`

Discover gradient parameters

**MCP tool:** `lr_develop_discover_gradient_parameters`  -  **bridge:** `develop.discoverGradientParameters`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

### `lr develop debug monitor`

Monitor parameter changes

**MCP tool:** `lr_develop_monitor_parameter_changes`  -  **bridge:** `develop.monitorParameterChanges`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `duration` | integer |  | `10` | Monitoring duration in seconds |

### `lr develop debug probe`

Probe all develop parameters

**MCP tool:** `lr_develop_probe_all_develop_parameters`  -  **bridge:** `develop.probeAllDevelopParameters`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

### `lr develop edit-in-photoshop`

Open current photo in Photoshop

**MCP tool:** `lr_develop_edit_in_photoshop`  -  **bridge:** `develop.editInPhotoshop`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop filter brush`

Create an adjustment brush

**MCP tool:** `lr_develop_create_adjustment_brush`  -  **bridge:** `develop.createAdjustmentBrush`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop filter graduated`

Create a graduated filter

**MCP tool:** `lr_develop_create_graduated_filter`  -  **bridge:** `develop.createGraduatedFilter`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop filter radial`

Create a radial filter

**MCP tool:** `lr_develop_create_radial_filter`  -  **bridge:** `develop.createRadialFilter`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop filter range`

Create a range mask

**MCP tool:** `lr_develop_create_range_mask`  -  **bridge:** `develop.createRangeMask`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `rangeType` | enum |  |  | Range mask type (one of: luminance, color, depth) |

### `lr develop get`

Get a single develop parameter value

**MCP tool:** `lr_develop_get_value`  -  **bridge:** `develop.getValue`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Parameter name |

**Response fields:** `parameter`, `value`

### `lr develop get-settings`

Get all current develop settings

**MCP tool:** `lr_develop_get_settings`  -  **bridge:** `develop.getSettings`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Target photo ID |

**Response fields:** `Exposure`, `Contrast`, `Highlights`, `Shadows`, `Whites`, `Blacks`, `Temperature`, `Tint`

### `lr develop local apply`

Apply multiple local adjustment settings

**MCP tool:** `lr_develop_apply_local_settings`  -  **bridge:** `develop.applyLocalSettings`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `settings` | json_object | yes |  | JSON object of local adjustment settings |
| `maskId` | string |  |  | Mask ID to select before applying settings |

### `lr develop local create-mask`

Create mask with local adjustments

**MCP tool:** `lr_develop_create_mask_with_local_adjustments`  -  **bridge:** `develop.createMaskWithLocalAdjustments`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `maskType` | enum |  |  | Mask type to create (one of: brush, gradient, radial) |
| `localSettings` | json_object |  |  | Local adjustment settings to apply to the mask |
| `maskSubtype` | string |  |  | Mask subtype passed to mask creation |

### `lr develop local get`

Get a local adjustment parameter value

**MCP tool:** `lr_develop_get_local_value`  -  **bridge:** `develop.getLocalValue`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Local adjustment parameter name (e.g., local_Exposure) |
| `maskId` | string |  |  | Mask ID to select before reading value |

**Response fields:** `parameter`, `value`

### `lr develop local params`

List available local adjustment parameters

**MCP tool:** `lr_develop_get_available_local_parameters`  -  **bridge:** `develop.getAvailableLocalParameters`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `parameters`

### `lr develop local set`

Set a local adjustment parameter value

**MCP tool:** `lr_develop_set_local_value`  -  **bridge:** `develop.setLocalValue`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Local adjustment parameter name |
| `value` | float | yes |  | Parameter value |
| `maskId` | string |  |  | Mask ID to select before setting value |

### `lr develop mask go-to`

Go to masking view

**MCP tool:** `lr_develop_go_to_masking`  -  **bridge:** `develop.goToMasking`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `status`

### `lr develop mask list`

List all masks

**MCP tool:** `lr_develop_get_all_masks`  -  **bridge:** `develop.getAllMasks`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `masks`, `count`

### `lr develop mask selected`

Get selected mask

**MCP tool:** `lr_develop_get_selected_mask`  -  **bridge:** `develop.getSelectedMask`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `mask`

### `lr develop mask toggle-overlay`

Toggle mask overlay

**MCP tool:** `lr_develop_toggle_overlay`  -  **bridge:** `develop.toggleOverlay`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

### `lr develop paste-settings`

Paste develop settings to selected photo

**MCP tool:** `lr_catalog_paste_settings`  -  **bridge:** `catalog.pasteSettings`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop preset`

Apply a develop preset by name

**MCP tool:** `lr_catalog_apply_develop_preset`  -  **bridge:** `catalog.applyDevelopPreset`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `presetName` | string | yes |  | Preset name to apply |

### `lr develop process-version`

Get the current process version

**MCP tool:** `lr_develop_get_process_version`  -  **bridge:** `develop.getProcessVersion`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `version`

### `lr develop range`

Get min/max range for a develop parameter

**MCP tool:** `lr_develop_get_range`  -  **bridge:** `develop.getRange`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Parameter name |

**Response fields:** `parameter`, `min`, `max`

### `lr develop reset`

Reset develop settings to defaults

**MCP tool:** `lr_develop_reset_all_develop_adjustments`  -  **bridge:** `develop.resetAllDevelopAdjustments`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-brush`

Reset adjustment brush

**MCP tool:** `lr_develop_reset_brushing`  -  **bridge:** `develop.resetBrushing`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-circular`

Reset circular gradient filter

**MCP tool:** `lr_develop_reset_circular_gradient`  -  **bridge:** `develop.resetCircularGradient`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-crop`

Reset crop

**MCP tool:** `lr_develop_reset_crop`  -  **bridge:** `develop.resetCrop`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-gradient`

Reset gradient filter

**MCP tool:** `lr_develop_reset_gradient`  -  **bridge:** `develop.resetGradient`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-healing`

Reset healing

**MCP tool:** `lr_develop_reset_healing`  -  **bridge:** `develop.resetHealing`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-masking`

Reset masking

**MCP tool:** `lr_develop_reset_masking`  -  **bridge:** `develop.resetMasking`  -  **risk:** destructive  -  **timeout:** 30s  -  dry-run  -  **requires --confirm**

_No parameters._

### `lr develop reset-param`

Reset a develop parameter to its default value

**MCP tool:** `lr_develop_reset_to_default`  -  **bridge:** `develop.resetToDefault`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Develop parameter name to reset |

### `lr develop reset-redeye`

Reset red eye removal

**MCP tool:** `lr_develop_reset_redeye`  -  **bridge:** `develop.resetRedeye`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-spot`

Reset spot removal

**MCP tool:** `lr_develop_reset_spot_removal`  -  **bridge:** `develop.resetSpotRemoval`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop reset-transforms`

Reset transforms

**MCP tool:** `lr_develop_reset_transforms`  -  **bridge:** `develop.resetTransforms`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr develop set`

Set develop parameter(s)

**MCP tool:** `lr_develop_set_value`  -  **bridge:** `develop.setValue`  -  **risk:** write  -  **timeout:** 10s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `param` | string | yes |  | Develop parameter name (e.g., Exposure, Contrast) |
| `value` | scalar | yes |  | Parameter value (number, boolean, or string per the parameter) |

**Response fields:** `parameter`, `value`, `previousValue`

### `lr develop set-process-version`

Set the process version

**MCP tool:** `lr_develop_set_process_version`  -  **bridge:** `develop.setProcessVersion`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `version` | string | yes |  | Process version string (e.g., 6.7) |

### `lr develop snapshot`

Create a develop snapshot

**MCP tool:** `lr_catalog_create_develop_snapshot`  -  **bridge:** `catalog.createDevelopSnapshot`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes |  | Snapshot name |

### `lr develop tool`

Select a develop tool

**MCP tool:** `lr_develop_select_tool`  -  **bridge:** `develop.selectTool`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `tool` | enum | yes |  | Tool name (one of: loupe, crop, dust, redeye, gradient, circularGradient, localized, upright) |

**Response fields:** `tool`, `status`

## export

### `lr export files`

Export photos to disk via LrExportSession (long-running; default ORIGINAL passthrough)

**MCP tool:** `lr_catalog_export_photos`  -  **bridge:** `catalog.exportPhotos`  -  **risk:** write  -  **timeout:** 300s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array |  |  | Photo ID strings (localIdentifier); omit to use the current selection |
| `dest` | string | yes |  | Destination folder (absolute path on the Lightroom host) |
| `format` | enum |  | `ORIGINAL` | Export format (ORIGINAL = passthrough copy of the source file) (one of: ORIGINAL, JPEG, TIFF, PNG, DNG, PSD) |
| `quality` | integer |  |  | JPEG quality 0-100 (raster formats only; ignored for ORIGINAL) [min 0, max 100] |
| `resizeLongEdge` | integer |  |  | Resize so the long edge is N pixels (raster formats only) [min 1, max 65000] |
| `overwrite` | enum |  | `rename` | Existing-file behavior (no 'ask' -- would hang headless) (one of: skip, overwrite, rename) |
| `continueOnError` | boolean |  | `True` | Continue if an individual photo fails to render |

**Response fields:** `dest`, `format`, `exported`, `failed`, `results`, `total`

## plugin

### `lr plugin install`

Install the Lightroom plugin to Modules directory

**MCP tool:** `lr_plugin_install`  -  **bridge:** `plugin.install`  -  **risk:** write  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `dev` | boolean |  | `False` | Use symlink instead of copy (development mode) |

### `lr plugin status`

Show plugin installation status

**MCP tool:** `lr_plugin_status`  -  **bridge:** `plugin.status`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `source`, `target`, `status`

### `lr plugin uninstall`

Uninstall the Lightroom plugin

**MCP tool:** `lr_plugin_uninstall`  -  **bridge:** `plugin.uninstall`  -  **risk:** write  -  **timeout:** 30s

_No parameters._

## preview

### `lr preview generate`

Generate preview with specified size and format

**MCP tool:** `lr_preview_generate_preview`  -  **bridge:** `preview.generatePreview`  -  **risk:** read  -  **timeout:** 120s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Target photo ID |
| `size` | string |  |  | Preview size: small, medium, large, or custom number |
| `quality` | integer |  |  | JPEG quality (default: 90) |
| `format` | string |  |  | Output format (default: jpeg) |
| `base64` | boolean |  |  | Base64 encode output (default: true) |

**Response fields:** `path`, `size`, `format`

### `lr preview generate-batch`

Generate batch previews

**MCP tool:** `lr_preview_generate_batch_previews`  -  **bridge:** `preview.generateBatchPreviews`  -  **risk:** read  -  **timeout:** 300s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoIds` | json_array | yes |  | Array of photo IDs |
| `size` | string |  |  | Preview size: small, medium, large, or custom number |
| `quality` | integer |  |  | JPEG quality (default: 90) |
| `base64` | boolean |  |  | Base64 encode output (default: true) |

**Response fields:** `previews`, `total`

### `lr preview info`

Get preview info for a photo

**MCP tool:** `lr_preview_get_preview_info`  -  **bridge:** `preview.getPreviewInfo`  -  **risk:** read  -  **timeout:** 30s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `photoId` | string | yes |  | Photo ID to get preview info for |

**Response fields:** `photoId`, `path`, `size`, `exists`

## selection

### `lr selection color-label`

Set color label for selected photo(s)

**MCP tool:** `lr_selection_set_color_label`  -  **bridge:** `selection.setColorLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `label` | enum | yes |  | Color label to set (one of: red, yellow, green, blue, purple, none) |

### `lr selection decrease-rating`

Decrease rating by 1

**MCP tool:** `lr_selection_decrease_rating`  -  **bridge:** `selection.decreaseRating`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection deselect-active`

Deselect the active photo

**MCP tool:** `lr_selection_deselect_active`  -  **bridge:** `selection.deselectActive`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection deselect-others`

Deselect all except active photo

**MCP tool:** `lr_selection_deselect_others`  -  **bridge:** `selection.deselectOthers`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection extend`

Extend selection in a direction

**MCP tool:** `lr_selection_extend_selection`  -  **bridge:** `selection.extendSelection`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `direction` | enum |  | `right` | Direction to extend selection (one of: left, right) |
| `amount` | integer |  | `1` | Number of photos to extend by |

### `lr selection flag`

Flag selected photo(s) as Pick

**MCP tool:** `lr_selection_flag_as_pick`  -  **bridge:** `selection.flagAsPick`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection get-color-label`

Get color label of selected photo

**MCP tool:** `lr_selection_get_color_label`  -  **bridge:** `selection.getColorLabel`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `label`

### `lr selection get-flag`

Get flag status of selected photo

**MCP tool:** `lr_selection_get_flag`  -  **bridge:** `selection.getFlag`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `flag`

### `lr selection get-rating`

Get rating of selected photo

**MCP tool:** `lr_selection_get_rating`  -  **bridge:** `selection.getRating`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `rating`

### `lr selection increase-rating`

Increase rating by 1

**MCP tool:** `lr_selection_increase_rating`  -  **bridge:** `selection.increaseRating`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection next`

Move to next photo

**MCP tool:** `lr_selection_next_photo`  -  **bridge:** `selection.nextPhoto`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `status`

### `lr selection previous`

Move to previous photo

**MCP tool:** `lr_selection_previous_photo`  -  **bridge:** `selection.previousPhoto`  -  **risk:** read  -  **timeout:** 30s

_No parameters._

**Response fields:** `status`

### `lr selection reject`

Flag selected photo(s) as Reject

**MCP tool:** `lr_selection_flag_as_reject`  -  **bridge:** `selection.flagAsReject`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection select-all`

Select all photos

**MCP tool:** `lr_selection_select_all`  -  **bridge:** `selection.selectAll`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection select-inverse`

Invert the current selection

**MCP tool:** `lr_selection_select_inverse`  -  **bridge:** `selection.selectInverse`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection select-none`

Deselect all photos

**MCP tool:** `lr_selection_select_none`  -  **bridge:** `selection.selectNone`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection set-rating`

Set rating for selected photo (0-5)

**MCP tool:** `lr_selection_set_rating`  -  **bridge:** `selection.setRating`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `rating` | integer | yes |  | Rating 0-5 [min 0, max 5] |

### `lr selection toggle-blue-label`

Toggle blue label for selected photo(s)

**MCP tool:** `lr_selection_toggle_blue_label`  -  **bridge:** `selection.toggleBlueLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection toggle-green-label`

Toggle green label for selected photo(s)

**MCP tool:** `lr_selection_toggle_green_label`  -  **bridge:** `selection.toggleGreenLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection toggle-purple-label`

Toggle purple label for selected photo(s)

**MCP tool:** `lr_selection_toggle_purple_label`  -  **bridge:** `selection.togglePurpleLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection toggle-red-label`

Toggle red label for selected photo(s)

**MCP tool:** `lr_selection_toggle_red_label`  -  **bridge:** `selection.toggleRedLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection toggle-yellow-label`

Toggle yellow label for selected photo(s)

**MCP tool:** `lr_selection_toggle_yellow_label`  -  **bridge:** `selection.toggleYellowLabel`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

### `lr selection unflag`

Remove flag from selected photo(s)

**MCP tool:** `lr_selection_remove_flag`  -  **bridge:** `selection.removeFlag`  -  **risk:** write  -  **timeout:** 30s  -  dry-run

_No parameters._

## system

### `lr system check-connection`

Check if Lightroom is available

**MCP tool:** `lr_system_check_connection`  -  **bridge:** `system.checkConnection`  -  **risk:** read  -  **timeout:** 5s

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `portFile` | string |  |  | Path to port file (default: auto-detect) |

**Response fields:** `status`, `reason`

### `lr system ping`

Test connection

**MCP tool:** `lr_system_ping`  -  **bridge:** `system.ping`  -  **risk:** read  -  **timeout:** 5s

_No parameters._

**Response fields:** `status`, `timestamp`

### `lr system reconnect`

Force reconnection to Lightroom

**MCP tool:** `lr_system_reconnect`  -  **bridge:** `system.reconnect`  -  **risk:** read  -  **timeout:** 10s

_No parameters._

**Response fields:** `status`

### `lr system status`

Get bridge status

**MCP tool:** `lr_system_status`  -  **bridge:** `system.status`  -  **risk:** read  -  **timeout:** 5s

_No parameters._

**Response fields:** `status`, `uptime`, `version`, `connections`


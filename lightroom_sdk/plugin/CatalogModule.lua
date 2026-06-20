-- CatalogModule.lua
-- Catalog operations API wrapper for Phase 4
-- Enhanced with lightweight error handling

-- Lazy imports to avoid loading issues
local LrApplication = nil
local LrTasks = import 'LrTasks'
local LrDate = nil
local LrProgressScope = nil
local LrExportSession = nil
local LrFileUtils = nil
local LrPathUtils = nil

-- Get ErrorUtils from global state (created in PluginInit.lua)
local function getErrorUtils()
    if _G.LightroomPythonBridge and _G.LightroomPythonBridge.ErrorUtils then
        return _G.LightroomPythonBridge.ErrorUtils
    end
    -- Minimal fallback if global not available
    return {
        safeCall = function(func, ...) return LrTasks.pcall(func, ...) end,
        createError = function(code, message) return { error = { code = code or "ERROR", message = message or "An error occurred", severity = "error" } } end,
        createSuccess = function(result) return { result = result or {} } end,
        wrapCallback = function(callback) return callback end,
        validateRequired = function() return true end,
        CODES = { MISSING_PARAM = "MISSING_PARAM", CATALOG_ACCESS_FAILED = "CATALOG_ACCESS_FAILED" }
    }
end

local ErrorUtils = getErrorUtils()

-- Lazy load Lightroom modules
local function ensureLrModules()
    if not LrApplication then
        LrApplication = import 'LrApplication'
    end
    if not LrProgressScope then
        LrProgressScope = import 'LrProgressScope'
    end
    if not LrDate then
        local success, dateModule = ErrorUtils.safeCall(import, 'LrDate')
        if success and dateModule then
            LrDate = dateModule
        end
    end
    if not LrFileUtils then
        LrFileUtils = import 'LrFileUtils'
    end
    if not LrPathUtils then
        LrPathUtils = import 'LrPathUtils'
    end
    if not LrExportSession then
        LrExportSession = import 'LrExportSession'
    end
end

-- Get logger from global state (defensive)
local function getLogger()
    if _G.LightroomPythonBridge and _G.LightroomPythonBridge.logger then
        return _G.LightroomPythonBridge.logger
    end
    local LrLogger = import 'LrLogger'
    local logger = LrLogger('CatalogModule')
    logger:enable("logfile")
    return logger
end

local CatalogModule = {}

-- Search photos (deprecated: delegates to findPhotos)
function CatalogModule.searchPhotos(params, callback)
    local logger = getLogger()
    logger:warn("deprecated: searchPhotos は findPhotos に統合されました。次バージョンで削除予定。")

    -- Convert criteria to searchDesc format
    local criteria = (params and params.criteria) or {}
    local searchDesc = {}
    for k, v in pairs(criteria) do
        searchDesc[k] = v
    end

    local findParams = {
        searchDesc = searchDesc,
        limit = (params and params.limit) or 100,
        offset = (params and params.offset) or 0,
    }

    CatalogModule.findPhotos(findParams, function(response)
        -- Add legacy hasMore field for backward compatibility
        local r = response and response.result
        if r and r.photos then
            local total = r.total or 0
            local off = r.offset or 0
            local returned = r.returned or #r.photos
            r.hasMore = (off + returned) < total
        end
        callback(response)
    end)
end

-- Get photo metadata
function CatalogModule.getPhotoMetadata(params, callback)
    ensureLrModules()
    local logger = getLogger()
    
    local photoId = nil
    
    -- Safe parameter extraction with error handling
    local success, result = ErrorUtils.safeCall(function()
        logger:debug("getPhotoMetadata called with params: " .. tostring(params))
        
        if params then
            logger:debug("params is a table with type: " .. type(params))
            local count = 0
            for k, v in pairs(params) do
                logger:debug("  param[" .. tostring(k) .. "] = " .. tostring(v) .. " (type: " .. type(v) .. ")")
                count = count + 1
            end
            logger:debug("Total params count: " .. count)
            
            photoId = params.photoId
        else
            logger:error("params is nil!")
        end
        
        logger:debug("Extracted photoId: " .. tostring(photoId))
        return photoId
    end)
    
    if not success then
        logger:error("Error in parameter extraction: " .. tostring(result))
    else
        photoId = result
    end
    
    if not photoId then
        callback({
            error = {
                code = "MISSING_PHOTO_ID",
                message = "Photo ID is required"
            }
        })
        return
    end
    
    logger:debug("Getting metadata for photo: " .. photoId)
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        -- Find photo by localIdentifier
        local photo = catalog:getPhotoByLocalId(tonumber(photoId))
        
        if not photo then
            callback({
                error = {
                    code = "PHOTO_NOT_FOUND",
                    message = "Photo with ID " .. photoId .. " not found"
                }
            })
            return
        end
        
        -- Collect comprehensive metadata
        local rawRating = photo:getRawMetadata("rating")
        logger:debug("Raw rating value: " .. tostring(rawRating) .. " (type: " .. type(rawRating) .. ")")
        
        local metadata = {
            -- Basic info
            id = photo.localIdentifier,
            filename = photo:getFormattedMetadata("fileName"),
            folderPath = photo:getFormattedMetadata("folderName"),
            filepath = photo:getRawMetadata("path"),
            fileSize = photo:getFormattedMetadata("fileSize"),
            fileFormat = photo:getRawMetadata("fileFormat"),
            
            -- Capture info
            captureTime = photo:getFormattedMetadata("dateTimeOriginal"),
            cameraMake = photo:getFormattedMetadata("cameraMake"),
            cameraModel = photo:getFormattedMetadata("cameraModel"),
            lens = photo:getFormattedMetadata("lens"),
            
            -- Settings
            iso = photo:getFormattedMetadata("isoSpeedRating"),
            aperture = photo:getFormattedMetadata("aperture"),
            shutterSpeed = photo:getFormattedMetadata("shutterSpeed"),
            focalLength = photo:getFormattedMetadata("focalLength"),
            
            -- Lightroom specific
            rating = rawRating or 0,  -- Default to 0 if nil
            colorLabel = photo:getRawMetadata("colorNameForLabel"),
            pickStatus = photo:getRawMetadata("pickStatus"),
            isVirtualCopy = photo:getRawMetadata("isVirtualCopy"),
            stackPosition = photo:getRawMetadata("stackPositionInFolder"),
            
            -- Develop status (use basic metadata only)
            -- hasAdjustments/hasCrop not available in all Lightroom versions
            
            -- Keywords and collections
            keywords = {},
            collections = {}
        }
        
        logger:debug("Metadata table rating: " .. tostring(metadata.rating))
        
        -- Get keywords
        local keywords = photo:getRawMetadata("keywords")
        if keywords then
            for _, keyword in ipairs(keywords) do
                table.insert(metadata.keywords, {
                    name = keyword:getName(),
                    synonyms = keyword:getSynonyms()
                })
            end
        end
        
        -- Get collections
        local collections = photo:getContainedCollections()
        if collections then
            for _, collection in ipairs(collections) do
                table.insert(metadata.collections, {
                    name = collection:getName(),
                    type = collection:type()
                })
            end
        end
        
        logger:info("Retrieved metadata for photo: " .. metadata.filename)
        logger:debug("About to send metadata with rating: " .. tostring(metadata.rating))
        
        callback({
            result = metadata
        })
    end)
end

-- Resolve the effective selection from the catalog's target photo(s).
-- LrCatalog:getTargetPhotos() returns the WHOLE FILMSTRIP when nothing is selected, so
-- gate on getTargetPhoto() (singular, the active photo): nil => nothing is truly selected.
-- Pure + side-effect-free so it is unit-testable without a live Lightroom.
function CatalogModule._resolveSelection(targetPhoto, targetPhotos)
    if targetPhoto == nil then
        return {}
    end
    return targetPhotos or {}
end

-- Get current selection
function CatalogModule.getSelectedPhotos(params, callback)
    local wrappedCallback = ErrorUtils.wrapCallback(callback, "getSelectedPhotos")
    
    -- Ensure modules are loaded
    local moduleSuccess, moduleError = ErrorUtils.safeCall(ensureLrModules)
    if not moduleSuccess then
        wrappedCallback(ErrorUtils.createError(ErrorUtils.CODES.RESOURCE_UNAVAILABLE, 
            "Failed to load Lightroom modules: " .. tostring(moduleError)))
        return
    end
    
    local logger = getLogger()
    logger:debug("Getting currently selected photos")
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local targetPhotoSuccess, targetPhoto = ErrorUtils.safeCall(function()
            return catalog:getTargetPhoto()
        end)
        local selectedSuccess, targetPhotos = ErrorUtils.safeCall(function()
            return catalog:getTargetPhotos()
        end)

        -- getTargetPhotos() is the whole filmstrip when nothing is selected; gate on the
        -- singular active photo so "get selected" never reports the entire catalog.
        local selectedPhotos = CatalogModule._resolveSelection(
            (targetPhotoSuccess and targetPhoto) or nil,
            (selectedSuccess and targetPhotos) or nil
        )

        if #selectedPhotos == 0 then
            wrappedCallback(ErrorUtils.createSuccess({
                photos = {},
                count = 0
            }, "No photos currently selected"))
            return
        end
        
        local results = {}
        
        for i, photo in ipairs(selectedPhotos) do
            local photoData = {
                id = photo.localIdentifier
            }
            
            -- Safely get photo metadata
            ErrorUtils.safeCall(function()
                photoData.filename = photo:getFormattedMetadata("fileName")
                photoData.folderPath = photo:getFormattedMetadata("folderName")
                photoData.path = photo:getRawMetadata("path")
                photoData.captureTime = photo:getFormattedMetadata("dateTimeOriginal")
                photoData.rating = photo:getRawMetadata("rating")
                photoData.pickStatus = photo:getRawMetadata("pickStatus")
                photoData.fileFormat = photo:getRawMetadata("fileFormat")
                photoData.isVirtualCopy = photo:getRawMetadata("isVirtualCopy")
            end)

            table.insert(results, photoData)
        end
        
        logger:info("Retrieved " .. #results .. " selected photos")
        
        wrappedCallback(ErrorUtils.createSuccess({
            photos = results,
            count = #results
        }, "Selected photos retrieved successfully"))
    end)
end

-- Set photo selection
function CatalogModule.setSelectedPhotos(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoIds = params.photoIds
    
    if not photoIds or type(photoIds) ~= "table" then
        callback({
            error = {
                code = "INVALID_PHOTO_IDS",
                message = "Photo IDs array is required"
            }
        })
        return
    end
    
    logger:debug("Setting photo selection to " .. #photoIds .. " photos")
    
    local catalog = LrApplication.activeCatalog()
    
    -- Use withWriteAccessDo with timeout to prevent blocking
    local selectResult = nil
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Photo Selection", function()
            local photos = {}
            local notFound = {}

            -- Find all photos by localIdentifier
            for _, photoId in ipairs(photoIds) do
                local photo = catalog:getPhotoByLocalId(tonumber(photoId))
                if photo then
                    table.insert(photos, photo)
                else
                    table.insert(notFound, photoId)
                end
            end

            if #photos == 0 then
                error("No photos found with provided IDs")
            end

            -- Set selection
            catalog:setSelectedPhotos(photos[1], photos)

            selectResult = {
                selected = #photos,
                notFound = #notFound > 0 and notFound or nil
            }
        end, { timeout = 10 })  -- 10 second timeout
    end)

    if writeSuccess and selectResult then
        logger:info("Successfully set selection to " .. selectResult.selected .. " photos")
        callback({
            result = selectResult
        })
    else
        logger:error("Failed to set photo selection: " .. tostring(writeError))
        callback({
            error = {
                code = "WRITE_ACCESS_BLOCKED",
                message = "Failed to set photo selection: " .. tostring(writeError)
            }
        })
    end
end

-- Get all photos in catalog
function CatalogModule.getAllPhotos(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local limit = params.limit or 1000  -- Default limit to prevent memory issues
    local offset = params.offset or 0
    
    logger:debug("Getting all photos from catalog")
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local allPhotos = catalog:getAllPhotos()
        
        if not allPhotos then
            callback({
                error = {
                    code = "NO_PHOTOS",
                    message = "No photos found in catalog"
                }
            })
            return
        end
        
        logger:info("Found " .. #allPhotos .. " total photos in catalog")
        
        -- Apply pagination
        local startIndex = offset + 1
        local endIndex = math.min(startIndex + limit - 1, #allPhotos)
        local pagedPhotos = {}
        
        for i = startIndex, endIndex do
            local photo = allPhotos[i]
            table.insert(pagedPhotos, {
                id = photo.localIdentifier,
                filename = photo:getFormattedMetadata("fileName"),
                path = photo:getRawMetadata("path"),
                captureTime = photo:getFormattedMetadata("dateTimeOriginal"),
                fileFormat = photo:getRawMetadata("fileFormat"),
                rating = photo:getRawMetadata("rating"),
                pickStatus = photo:getRawMetadata("pickStatus")
            })
        end
        
        callback({
            result = {
                photos = pagedPhotos,
                total = #allPhotos,
                offset = offset,
                limit = limit,
                returned = #pagedPhotos
            }
        })
    end)
end

-- Find photo by file path
function CatalogModule.findPhotoByPath(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local path = params.path
    
    if not path then
        callback({
            error = {
                code = "MISSING_PATH",
                message = "File path is required"
            }
        })
        return
    end
    
    logger:debug("Finding photo by path: " .. path)
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local photo = catalog:findPhotoByPath(path)
        
        if not photo then
            callback({
                error = {
                    code = "PHOTO_NOT_FOUND",
                    message = "No photo found at path: " .. path
                }
            })
            return
        end
        
        callback({
            result = {
                id = photo.localIdentifier,
                filename = photo:getFormattedMetadata("fileName"),
                path = photo:getRawMetadata("path"),
                captureTime = photo:getFormattedMetadata("dateTimeOriginal"),
                fileFormat = photo:getRawMetadata("fileFormat"),
                rating = photo:getRawMetadata("rating"),
                camera = photo:getFormattedMetadata("cameraModel")
            }
        })
    end)
end

-- Known filter keys for findPhotos
local KNOWN_FILTER_KEYS = {
    flag = true, rating = true, ratingOp = true, colorLabel = true, camera = true,
    folderPath = true, captureDateFrom = true, captureDateTo = true,
    fileFormat = true, keyword = true, filename = true, text = true,
}

-- Returns a sorted list of filter keys in searchDesc that are not recognized, or nil
-- if all are known. Pure (no SDK) so it is unit-testable. findPhotos uses this to fail
-- closed: an unknown key must NOT fall through to an empty predicate that matches every
-- photo (that returned the entire catalog as a "search result" -- the legacy `search`
-- path sent {query=...}).
function CatalogModule._unknownFilterKeys(searchDesc)
    if type(searchDesc) ~= "table" then return nil end
    local unknown = {}
    for key, _ in pairs(searchDesc) do
        if not KNOWN_FILTER_KEYS[key] then
            table.insert(unknown, tostring(key))
        end
    end
    if #unknown == 0 then return nil end
    table.sort(unknown)
    return unknown
end

-- Chunk processing constants
local FILTER_CHUNK_SIZE = 50
local METADATA_CHUNK_SIZE = 50
local DEFAULT_PAGE_SIZE = 500
local MAX_PAGE_SIZE = 2000

-- Get CommandRouter from global state for abort checking
local function getCommandRouter()
    if _G.LightroomPythonBridge and _G.LightroomPythonBridge.commandRouter then
        return _G.LightroomPythonBridge.commandRouter
    end
    return nil
end

-- Match a single photo against search criteria
local function matchPhoto(photo, searchDesc)
    -- Light filters first --

    -- Rating filter
    if searchDesc.rating then
        local rating = photo:getRawMetadata("rating") or 0
        local op = searchDesc.ratingOp or "=="
        if op == "==" and rating ~= searchDesc.rating then return false end
        if op == ">=" and rating < searchDesc.rating then return false end
        if op == "<=" and rating > searchDesc.rating then return false end
        if op == ">" and rating <= searchDesc.rating then return false end
        if op == "<" and rating >= searchDesc.rating then return false end
    end

    -- Flag filter
    if searchDesc.flag then
        local pickStatus = photo:getRawMetadata("pickStatus") or 0
        if searchDesc.flag == "pick" and pickStatus ~= 1 then return false end
        if searchDesc.flag == "reject" and pickStatus ~= -1 then return false end
        if searchDesc.flag == "none" and pickStatus ~= 0 then return false end
    end

    -- Color label filter
    if searchDesc.colorLabel then
        local label = photo:getRawMetadata("colorNameForLabel") or ""
        if searchDesc.colorLabel == "none" then
            if label ~= "" and label ~= "none" then return false end
        else
            if label ~= searchDesc.colorLabel then return false end
        end
    end

    -- File format filter (exact match)
    if searchDesc.fileFormat then
        local fmt = photo:getRawMetadata("fileFormat") or ""
        if fmt ~= searchDesc.fileFormat then return false end
    end

    -- Heavy filters --

    -- Camera filter
    if searchDesc.camera then
        local camera = photo:getFormattedMetadata("cameraModel") or ""
        if not string.find(string.lower(camera), string.lower(searchDesc.camera)) then
            return false
        end
    end

    -- Capture date range filter (use raw date + W3C format for locale-independent comparison)
    if searchDesc.captureDateFrom or searchDesc.captureDateTo then
        local rawDate = photo:getRawMetadata("dateTimeOriginal")
        if rawDate then
            local isoDate
            if LrDate and LrDate.timeToW3CDate then
                isoDate = LrDate.timeToW3CDate(rawDate)
            else
                isoDate = photo:getFormattedMetadata("dateTimeOriginal") or ""
            end
            if searchDesc.captureDateFrom and isoDate < searchDesc.captureDateFrom then
                return false
            end
            if searchDesc.captureDateTo then
                local upperBound = searchDesc.captureDateTo
                -- If date-only (YYYY-MM-DD), make it inclusive by appending end-of-day
                if #upperBound == 10 then
                    upperBound = upperBound .. "T23:59:59"
                end
                if isoDate > upperBound then
                    return false
                end
            end
        else
            return false
        end
    end

    -- Folder path filter (substring match)
    if searchDesc.folderPath then
        local path = photo:getRawMetadata("path") or ""
        if not string.find(path, searchDesc.folderPath, 1, true) then
            return false
        end
    end

    -- Filename filter (substring match)
    if searchDesc.filename then
        local fname = photo:getFormattedMetadata("fileName") or ""
        if not string.find(fname, searchDesc.filename, 1, true) then
            return false
        end
    end

    -- Free-text filter: case-insensitive substring across filename, title, caption. Uses RAW metadata
    -- (filename = basename of the raw path) so a full-catalog scan stays fast. Keyword text is the
    -- separate indexed `keyword` filter -- scanning keyword names per photo would dominate the cost.
    if searchDesc.text and searchDesc.text ~= "" then
        local needle = string.lower(searchDesc.text)
        local path = photo:getRawMetadata("path") or ""
        local fname = path:match("[^\\/]+$") or ""
        if not (string.find(string.lower(fname), needle, 1, true)
            or string.find(string.lower(photo:getRawMetadata("title") or ""), needle, 1, true)
            or string.find(string.lower(photo:getRawMetadata("caption") or ""), needle, 1, true)) then
            return false
        end
    end

    -- Keyword filter (substring match on keyword names)
    if searchDesc.keyword then
        local keywords = photo:getRawMetadata("keywords") or {}
        local keywordMatch = false
        for _, kw in ipairs(keywords) do
            local kwName = kw:getName()
            if string.find(string.lower(kwName), string.lower(searchDesc.keyword), 1, true) then
                keywordMatch = true
                break
            end
        end
        if not keywordMatch then return false end
    end

    return true
end

-- Pure: recursively collect every keyword whose name contains `substr` (case-insensitive).
-- Each element responds to :getName() and optionally :getChildren(). Unit-testable.
function CatalogModule._collectKeywordsMatching(keywords, substr)
    local matches = {}
    if type(keywords) ~= "table" or substr == nil then return matches end
    local needle = string.lower(substr)
    local function visit(list)
        for _, kw in ipairs(list) do
            if kw.getName and string.find(string.lower(kw:getName()), needle, 1, true) then
                table.insert(matches, kw)
            end
            if kw.getChildren then
                local children = kw:getChildren()
                if children then visit(children) end
            end
        end
    end
    visit(keywords)
    return matches
end

-- Candidate photos for a keyword substring via the keyword INDEX (keyword:getPhotos),
-- de-duplicated by localIdentifier. Avoids scanning the whole catalog for keyword
-- searches -- a keyword filter on a 30k+ catalog otherwise full-scans and exceeds the
-- command timeout (#9). Uses only SDK methods already proven in this module.
local function getKeywordCandidatePhotos(catalog, substr)
    local seen, photos = {}, {}
    catalog:withReadAccessDo(function()
        local matched = CatalogModule._collectKeywordsMatching(catalog:getKeywords(), substr)
        for _, kw in ipairs(matched) do
            for _, photo in ipairs(kw:getPhotos()) do
                local id = photo.localIdentifier
                if not seen[id] then
                    seen[id] = true
                    table.insert(photos, photo)
                end
            end
        end
    end)
    return photos
end

-- Advanced photo search with criteria
function CatalogModule.findPhotos(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local searchDesc = params.searchDesc or {}
    local limit = math.min(params.limit or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    local offset = math.max(params.offset or 0, 0)

    logger:debug("Finding photos with search criteria")

    -- Validate: fail closed on unknown filter keys. An unrecognized key must NOT
    -- silently match every photo -- that returned the entire catalog as a "search
    -- result" (the legacy `search` path sent {query=...}).
    local unknownKeys = CatalogModule._unknownFilterKeys(searchDesc)
    if unknownKeys then
        callback({
            error = {
                code = "INVALID_PARAM",
                message = "Unknown filter key(s): " .. table.concat(unknownKeys, ", ")
                    .. ". Valid keys: flag, rating, ratingOp, colorLabel, camera, folderPath, "
                    .. "captureDateFrom, captureDateTo, fileFormat, keyword, filename."
            }
        })
        return
    end
    local warnings = {}

    -- Validate: rating must be a number
    if searchDesc.rating ~= nil and type(searchDesc.rating) ~= "number" then
        callback({
            error = {
                code = "INVALID_PARAM",
                message = "rating must be a number"
            }
        })
        return
    end

    local catalog = LrApplication.activeCatalog()
    local partialErrors = {}
    local aborted = false
    local abortReason = nil
    local requestId = params._requestId
    local command = params._command or "catalog.findPhotos"
    local router = getCommandRouter()
    local streamMode = params._stream == true and router ~= nil and requestId ~= nil

    -- Step 1: Get candidate photos. For keyword searches use the keyword INDEX
    -- (keyword:getPhotos) instead of scanning every photo -- a keyword filter on a
    -- 30k+ catalog otherwise full-scans and exceeds the command timeout (#9). Other
    -- filters still scan.
    local usingKeywordIndex = type(searchDesc.keyword) == "string" and searchDesc.keyword ~= ""
    local allPhotos
    if usingKeywordIndex then
        allPhotos = getKeywordCandidatePhotos(catalog, searchDesc.keyword)
    else
        catalog:withReadAccessDo(function()
            allPhotos = catalog:getAllPhotos()
        end)
    end

    -- The keyword-index candidates already satisfy the keyword predicate, so drop it from
    -- the per-photo match -- re-reading every candidate's keywords was the slow step.
    local matchDesc = searchDesc
    if usingKeywordIndex then
        matchDesc = {}
        for k, v in pairs(searchDesc) do
            if k ~= "keyword" then matchDesc[k] = v end
        end
    end

    if not allPhotos or #allPhotos == 0 then
        callback({
            result = {
                photos = {},
                total = 0,
                returned = 0,
                offset = offset,
                limit = limit,
                warnings = #warnings > 0 and warnings or nil
            }
        })
        return
    end

    -- Step 2: Filter in chunks (yield between chunks to avoid blocking)
    local filtered = {}
    local totalPhotos = #allPhotos
    for chunkStart = 1, totalPhotos, FILTER_CHUNK_SIZE do
        -- Abort check at chunk boundary
        if router and requestId and router:shouldAbort(requestId, command) then
            aborted = true
            abortReason = router:isCancelled(requestId) and "cancelled" or "timeout"
            break
        end
        local chunkEnd = math.min(chunkStart + FILTER_CHUNK_SIZE - 1, totalPhotos)
        local chunkOk, chunkErr = LrTasks.pcall(function()
            catalog:withReadAccessDo(function()
                for i = chunkStart, chunkEnd do
                    if matchPhoto(allPhotos[i], matchDesc) then
                        table.insert(filtered, allPhotos[i])
                    end
                end
            end)
        end)
        if not chunkOk then
            table.insert(partialErrors, {
                chunk = chunkStart .. "-" .. chunkEnd,
                error = tostring(chunkErr)
            })
        end
        LrTasks.yield()
    end

    -- Step 3: Apply pagination
    local total = #filtered
    local startIndex = offset + 1
    local endIndex = math.min(offset + limit, total)
    local pagedPhotos = {}
    for i = startIndex, endIndex do
        table.insert(pagedPhotos, filtered[i])
    end

    -- Step 4: Build metadata in chunks (with optional NDJSON streaming)
    local resultPhotos = {}
    local streamedCount = 0
    if not aborted then
        for chunkStart = 1, #pagedPhotos, METADATA_CHUNK_SIZE do
            -- Abort check at chunk boundary
            if router and requestId and router:shouldAbort(requestId, command) then
                aborted = true
                abortReason = router:isCancelled(requestId) and "cancelled" or "timeout"
                break
            end
            local chunkEnd = math.min(chunkStart + METADATA_CHUNK_SIZE - 1, #pagedPhotos)
            local chunkPhotos = {}
            local chunkOk, chunkErr = LrTasks.pcall(function()
                catalog:withReadAccessDo(function()
                    for i = chunkStart, chunkEnd do
                        local photo = pagedPhotos[i]
                        local entry = {
                            id = photo.localIdentifier,
                            filename = photo:getFormattedMetadata("fileName"),
                            path = photo:getRawMetadata("path"),
                            captureTime = photo:getFormattedMetadata("dateTimeOriginal"),
                            fileFormat = photo:getRawMetadata("fileFormat"),
                            rating = photo:getRawMetadata("rating"),
                            pickStatus = photo:getRawMetadata("pickStatus"),
                            colorLabel = photo:getRawMetadata("colorNameForLabel")
                        }
                        table.insert(chunkPhotos, entry)
                        table.insert(resultPhotos, entry)
                    end
                end)
            end)
            if chunkOk then
                streamedCount = streamedCount + #chunkPhotos
                -- Send NDJSON streaming events if in stream mode
                if streamMode then
                    router:sendStreamEvent(requestId, "data", { photos = chunkPhotos })
                    router:sendStreamEvent(requestId, "progress", {
                        processed = streamedCount,
                        total = #pagedPhotos
                    })
                end
            else
                table.insert(partialErrors, {
                    chunk = "metadata " .. chunkStart .. "-" .. chunkEnd,
                    error = tostring(chunkErr)
                })
                if streamMode then
                    router:sendStreamEvent(requestId, "error", {
                        chunk = "metadata " .. chunkStart .. "-" .. chunkEnd,
                        error = tostring(chunkErr)
                    })
                end
            end
            LrTasks.yield()
        end
    end

    local responseResult = {
        photos = resultPhotos,
        total = total,
        returned = #resultPhotos,
        offset = offset,
        limit = limit,
        processedCount = #resultPhotos,
        totalCount = total,
        warnings = #warnings > 0 and warnings or nil
    }

    if aborted then
        responseResult.incomplete = true
        responseResult.reason = abortReason
    elseif #partialErrors > 0 then
        responseResult.incomplete = true
        responseResult.reason = "chunk_errors"
        responseResult.partialErrors = partialErrors
    end

    -- Send final streaming event if in stream mode
    if streamMode then
        router:sendStreamEvent(requestId, "final", {
            total = total,
            returned = #resultPhotos,
            processedCount = #resultPhotos,
            totalCount = total,
            incomplete = responseResult.incomplete,
            reason = responseResult.reason
        })
    end

    callback({ result = responseResult })
end

-- Get collections in catalog
-- Pure: recursively collect every collection from a node (catalog or collection set),
-- descending through child collection sets. Each node responds to :getChildCollections()
-- and :getChildCollectionSets(). Returns a flat array of collection objects. Unit-testable.
-- Fixes collections nested inside collection sets being unreachable (#163).
function CatalogModule._collectAllCollections(node)
    local result = {}
    if node == nil then return result end
    local function visit(n)
        if n.getChildCollections then
            for _, c in ipairs(n:getChildCollections()) do
                table.insert(result, c)
            end
        end
        if n.getChildCollectionSets then
            for _, s in ipairs(n:getChildCollectionSets()) do
                visit(s)
            end
        end
    end
    visit(node)
    return result
end

function CatalogModule.getCollections(params, callback)
    ensureLrModules()
    local logger = getLogger()

    logger:debug("Getting collections from catalog")

    local catalog = LrApplication.activeCatalog()
    local includePhotoCounts = params and params.includePhotoCounts

    local collections
    catalog:withReadAccessDo(function()
        collections = CatalogModule._collectAllCollections(catalog)
    end)

    local resultCollections = {}
    local COLLECTION_CHUNK_SIZE = 50
    for chunkStart = 1, #collections, COLLECTION_CHUNK_SIZE do
        local chunkEnd = math.min(chunkStart + COLLECTION_CHUNK_SIZE - 1, #collections)
        catalog:withReadAccessDo(function()
            for i = chunkStart, chunkEnd do
                local collection = collections[i]
                local entry = {
                    id = collection.localIdentifier,
                    name = collection:getName(),
                    type = collection:type(),
                }
                if includePhotoCounts then
                    entry.photoCount = #collection:getPhotos()
                end
                table.insert(resultCollections, entry)
            end
        end)
        LrTasks.yield()
    end

    callback({
        result = {
            collections = resultCollections,
            count = #resultCollections
        }
    })
end

-- Get keywords in catalog
function CatalogModule.getKeywords(params, callback)
    ensureLrModules()
    local logger = getLogger()
    
    logger:debug("Getting keywords from catalog")
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local keywords = catalog:getKeywords()
        
        local resultKeywords = {}
        for _, keyword in ipairs(keywords) do
            table.insert(resultKeywords, {
                id = keyword.localIdentifier,
                name = keyword:getName(),
                photoCount = #keyword:getPhotos()
            })
        end
        
        callback({
            result = {
                keywords = resultKeywords,
                count = #resultKeywords
            }
        })
    end)
end

-- Get folders in catalog
function CatalogModule.getFolders(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local includeSubfolders = params.includeSubfolders or false
    
    logger:debug("Getting folders from catalog")
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local rootFolders = catalog:getFolders()
        
        local function buildFolderTree(folder, depth)
            depth = depth or 0
            local folderPath = folder:getPath()
            local folderData = {
                id = folderPath, -- Use path as ID since folders don't have localIdentifier
                name = folder:getName(),
                path = folderPath,
                type = folder:type(),
                depth = depth,
                photoCount = #folder:getPhotos(false), -- Photos directly in this folder
                totalPhotoCount = #folder:getPhotos(true), -- Photos including subfolders
                subfolders = {}
            }
            
            -- Get parent folder info if available
            local parent = folder:getParent()
            if parent then
                folderData.parentId = parent:getPath()
                folderData.parentName = parent:getName()
            end
            
            -- Recursively get subfolders if requested
            if includeSubfolders then
                local children = folder:getChildren()
                if children then
                    for _, child in ipairs(children) do
                        table.insert(folderData.subfolders, buildFolderTree(child, depth + 1))
                    end
                end
            end
            
            return folderData
        end
        
        local resultFolders = {}
        for _, folder in ipairs(rootFolders) do
            table.insert(resultFolders, buildFolderTree(folder))
        end
        
        logger:info("Retrieved " .. #resultFolders .. " root folders from catalog")
        
        callback({
            result = {
                folders = resultFolders,
                count = #resultFolders,
                includeSubfolders = includeSubfolders
            }
        })
    end)
end

-- Batch get formatted metadata for multiple photos
function CatalogModule.batchGetFormattedMetadata(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoIds = params.photoIds
    local keys = params.keys or {"fileName", "dateTimeOriginal", "rating"}
    
    logger:debug("Batch metadata - photoIds type: " .. type(photoIds))
    if photoIds then
        logger:debug("Batch metadata - photoIds length: " .. tostring(#photoIds))
        if type(photoIds) == "table" then
            for i, id in ipairs(photoIds) do
                logger:debug("  photoId[" .. i .. "] = " .. tostring(id) .. " (type: " .. type(id) .. ")")
            end
        end
    end
    
    if not photoIds then
        callback({
            error = {
                code = "MISSING_PHOTO_IDS", 
                message = "Photo IDs parameter is missing"
            }
        })
        return
    end
    
    if type(photoIds) ~= "table" then
        callback({
            error = {
                code = "INVALID_PHOTO_IDS_TYPE",
                message = "Photo IDs must be an array, got: " .. type(photoIds)
            }
        })
        return
    end
    
    if #photoIds == 0 then
        callback({
            error = {
                code = "EMPTY_PHOTO_IDS",
                message = "Photo IDs array is empty"
            }
        })
        return
    end
    
    logger:debug("Batch getting metadata for " .. #photoIds .. " photos")
    logger:debug("Keys type: " .. type(keys))
    if type(keys) == "table" then
        logger:debug("Keys length: " .. #keys)
        for i, key in ipairs(keys) do
            logger:debug("  key[" .. i .. "] = " .. tostring(key))
        end
    else
        logger:debug("Keys value: " .. tostring(keys))
    end
    
    local catalog = LrApplication.activeCatalog()
    
    catalog:withReadAccessDo(function()
        local photos = {}
        for _, photoId in ipairs(photoIds) do
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if photo then
                table.insert(photos, photo)
            end
        end
        
        if #photos == 0 then
            callback({
                result = {
                    metadata = {},
                    requested = #photoIds,
                    found = 0
                }
            })
            return
        end
        
        -- Use batch API for efficiency
        local batchResults = catalog:batchGetFormattedMetadata(photos, keys)
        
        local results = {}
        for _, photo in ipairs(photos) do
            local metadata = {}
            local photoMeta = batchResults[photo]
            if photoMeta then
                for k, v in pairs(photoMeta) do
                    metadata[k] = v
                end
            end
            metadata.id = photo.localIdentifier
            table.insert(results, metadata)
        end
        
        callback({
            result = {
                metadata = results,
                requested = #photoIds,
                found = #photos,
                keys = keys
            }
        })
    end)
end

-- Set photo rating (Gap C fix)
function CatalogModule.setRating(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoId = params.photoId
    local rating = params.rating ~= nil and tonumber(params.rating) or nil

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if rating == nil or rating < 0 or rating > 5 then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "rating must be between 0 and 5"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Rating", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then error("Photo not found: " .. tostring(photoId)) end
            -- LR API: setRawMetadata("rating", 0) throws; use nil for unrated
            local ratingValue = rating
            if rating == 0 then ratingValue = nil end
            photo:setRawMetadata("rating", ratingValue)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({ photoId = photoId, rating = rating, message = "Rating set successfully" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set rating: " .. tostring(writeError)))
    end
end

-- Add keywords to photo (Gap C fix)
-- Recursively find an existing keyword by exact name in a keyword list (each element
-- responds to :getName() and optionally :getChildren()). Returns the keyword or nil.
-- Pure (no catalog access) so it is unit-testable. addKeywords uses it to reuse an
-- existing keyword object instead of catalog:createKeyword(name, {}, false, nil, true),
-- whose parent-scoped reuse is unreliable and silently spawns duplicate keyword objects.
function CatalogModule._findKeywordByName(keywords, name)
    if type(keywords) ~= "table" or name == nil then return nil end
    for _, kw in ipairs(keywords) do
        if kw.getName and kw:getName() == name then
            return kw
        end
        if kw.getChildren then
            local found = CatalogModule._findKeywordByName(kw:getChildren(), name)
            if found then return found end
        end
    end
    return nil
end

function CatalogModule.addKeywords(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoId = params.photoId
    local keywords = params.keywords

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if not keywords or type(keywords) ~= "table" or #keywords == 0 then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "keywords must be a non-empty array"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local addedKeywords = {}
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Add Keywords", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then error("Photo not found: " .. tostring(photoId)) end
            -- Reuse existing keyword objects (whole tree); only create when truly absent.
            -- catalog:createKeyword(parent=nil, returnIfExists) is parent-scoped and
            -- unreliable, so calling it blindly spawns duplicate keyword objects.
            local existingKeywords = catalog:getKeywords()
            local createdThisCall = {}
            for _, kwName in ipairs(keywords) do
                local keyword = createdThisCall[kwName]
                    or CatalogModule._findKeywordByName(existingKeywords, kwName)
                if not keyword then
                    keyword = catalog:createKeyword(kwName, {}, false, nil, true)
                    createdThisCall[kwName] = keyword
                end
                if keyword then
                    photo:addKeyword(keyword)
                    table.insert(addedKeywords, kwName)
                end
            end
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({ photoId = photoId, addedKeywords = addedKeywords, count = #addedKeywords, message = "Keywords added successfully" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to add keywords: " .. tostring(writeError)))
    end
end

-- Apply metadata fields (rating/colorLabel/flag/title/caption/addKeywords) to many photos in one
-- write transaction (one undo step). Photos resolved by id list or the current selection (filmstrip-
-- guarded). Per-photo continue-on-error; keyword objects resolved/created once for the whole batch.
function CatalogModule.batchSetMetadata(params, callback)
    ensureLrModules()
    params = params or {}
    local hasKeywords = type(params.addKeywords) == "table" and #params.addKeywords > 0
    local hasField = params.rating ~= nil or params.colorLabel ~= nil or params.flag ~= nil
        or params.title ~= nil or params.caption ~= nil or hasKeywords
    if not hasField then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE",
            "Provide at least one field to set (rating/colorLabel/flag/title/caption/addKeywords)"))
        return
    end
    -- Fail fast on bad scalar values (match the single setters' guards)
    if params.rating ~= nil then
        local rv = tonumber(params.rating)
        if rv == nil or rv < 0 or rv > 5 then
            callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "rating must be between 0 and 5"))
            return
        end
    end
    if params.flag ~= nil then
        local fv = tonumber(params.flag)
        if fv ~= 1 and fv ~= -1 and fv ~= 0 then
            callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "flag must be 1 (pick), -1 (reject), or 0 (none)"))
            return
        end
    end

    local catalog = LrApplication.activeCatalog()
    local photos, notFound = {}, {}
    local resolveOk, resolveErr = ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            if params.photoIds and type(params.photoIds) == "table" and #params.photoIds > 0 then
                for _, pid in ipairs(params.photoIds) do
                    local p = catalog:getPhotoByLocalId(tonumber(pid))
                    if p then table.insert(photos, p) else table.insert(notFound, tostring(pid)) end
                end
            else
                photos = CatalogModule._resolveSelection(catalog:getTargetPhoto(), catalog:getTargetPhotos())
            end
        end)
    end)
    if not resolveOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to resolve photos: " .. tostring(resolveErr)))
        return
    end
    if #photos == 0 then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photos to update (empty selection and no valid photoIds)"))
        return
    end

    local succeeded, failed, results = 0, 0, {}
    local writeOk, writeErr = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Batch Set Metadata", function()
            -- Resolve/create keyword objects ONCE for the whole batch (reuse-or-create per addKeywords).
            local keywordObjs = {}
            if hasKeywords then
                local existing = catalog:getKeywords()
                local created = {}
                for _, kwName in ipairs(params.addKeywords) do
                    local kw = created[kwName] or CatalogModule._findKeywordByName(existing, kwName)
                    if not kw then kw = catalog:createKeyword(kwName, {}, false, nil, true); created[kwName] = kw end
                    if kw then table.insert(keywordObjs, kw) end
                end
            end
            for _, photo in ipairs(photos) do
                local pid = tostring(photo.localIdentifier)
                local ok, err = ErrorUtils.safeCall(function()
                    if params.rating ~= nil then
                        local rv = tonumber(params.rating)
                        if rv == 0 then rv = nil end  -- LR: setRawMetadata("rating", 0) throws
                        photo:setRawMetadata("rating", rv)
                    end
                    if params.colorLabel ~= nil then photo:setRawMetadata("colorNameForLabel", params.colorLabel) end
                    if params.flag ~= nil then photo:setRawMetadata("pickStatus", tonumber(params.flag)) end
                    if params.title ~= nil then photo:setRawMetadata("title", params.title) end
                    if params.caption ~= nil then photo:setRawMetadata("caption", params.caption) end
                    for _, kw in ipairs(keywordObjs) do photo:addKeyword(kw) end
                end)
                if ok then
                    succeeded = succeeded + 1
                    table.insert(results, { photoId = pid, success = true })
                else
                    failed = failed + 1
                    table.insert(results, { photoId = pid, success = false, error = tostring(err) })
                end
            end
        end, { timeout = 30 })
    end)
    if not writeOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set metadata: " .. tostring(writeErr)))
        return
    end

    for _, pid in ipairs(notFound) do
        failed = failed + 1
        table.insert(results, { photoId = pid, success = false, error = "Photo not found" })
    end

    callback(ErrorUtils.createSuccess({
        total = #results, succeeded = succeeded, failed = failed, results = results,
    }))
end

-- Save catalog metadata to each photo's file (XMP). Photos by id list or current selection.
-- The READ direction (re-read file -> catalog) is intentionally NOT exposed: it overwrites catalog
-- edits with file values, which is unsafe when LR is the source of truth and auto-write-XMP is on.
function CatalogModule.saveMetadata(params, callback)
    ensureLrModules()
    params = params or {}
    local catalog = LrApplication.activeCatalog()
    local photos, notFound = {}, {}
    local resolveOk, resolveErr = ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            if params.photoIds and type(params.photoIds) == "table" and #params.photoIds > 0 then
                for _, pid in ipairs(params.photoIds) do
                    local p = catalog:getPhotoByLocalId(tonumber(pid))
                    if p then table.insert(photos, p) else table.insert(notFound, tostring(pid)) end
                end
            else
                photos = CatalogModule._resolveSelection(catalog:getTargetPhoto(), catalog:getTargetPhotos())
            end
        end)
    end)
    if not resolveOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to resolve photos: " .. tostring(resolveErr)))
        return
    end
    if #photos == 0 then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photos to save (empty selection and no valid photoIds)"))
        return
    end

    local succeeded, failed, results = 0, 0, {}
    for _, photo in ipairs(photos) do
        local pid = tostring(photo.localIdentifier)
        local ok, err = ErrorUtils.safeCall(function()
            photo:saveMetadata()  -- [SDK-VERIFY] writes catalog metadata to the file's XMP
        end)
        if ok then
            succeeded = succeeded + 1
            table.insert(results, { photoId = pid, success = true })
        else
            failed = failed + 1
            table.insert(results, { photoId = pid, success = false, error = tostring(err) })
        end
        LrTasks.yield()
    end

    for _, pid in ipairs(notFound) do
        failed = failed + 1
        table.insert(results, { photoId = pid, success = false, error = "Photo not found" })
    end

    callback(ErrorUtils.createSuccess({
        total = #results, succeeded = succeeded, failed = failed, results = results,
    }))
end

-- Import (add) existing files into the catalog via catalog:addPhoto. Paths must exist on disk; files
-- are referenced in place (not copied). Per-path partial success; new photo ids are read AFTER the
-- write txn (same SDK restriction as createCollection: can't read a just-added photo in the same txn).
function CatalogModule.importPhotos(params, callback)
    ensureLrModules()
    params = params or {}
    local paths = params.paths
    if type(paths) ~= "table" or #paths == 0 then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "paths must be a non-empty array"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local results, imported, failed = {}, 0, 0
    local addedPhotos = {}  -- resultIndex -> LrPhoto (ids read after the write commits)

    local writeOk, writeErr = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Import Photos", function()
            for _, path in ipairs(paths) do
                local p = tostring(path)
                if not LrFileUtils.exists(p) then
                    failed = failed + 1
                    table.insert(results, { path = p, success = false, error = "File not found" })
                else
                    local ok, photoOrErr = ErrorUtils.safeCall(function()
                        return catalog:addPhoto(p)  -- [SDK-VERIFY]
                    end)
                    if ok and photoOrErr then
                        imported = imported + 1
                        table.insert(results, { path = p, success = true })
                        addedPhotos[#results] = photoOrErr
                    else
                        failed = failed + 1
                        table.insert(results, { path = p, success = false, error = tostring(photoOrErr) })
                    end
                end
            end
        end, { timeout = 60 })
    end)
    if not writeOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Import failed: " .. tostring(writeErr)))
        return
    end

    -- Read new photo ids AFTER the write txn commits (best-effort; degrade to no id on failure)
    ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            for idx, photo in pairs(addedPhotos) do
                local ok, id = ErrorUtils.safeCall(function() return photo.localIdentifier end)
                if ok and id and results[idx] then results[idx].photoId = tostring(id) end
            end
        end)
    end)

    callback(ErrorUtils.createSuccess({ total = #results, imported = imported, failed = failed, results = results }))
end

-- Set photo flag (pick/reject/none)
function CatalogModule.setFlag(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoId = params.photoId
    local flag = params.flag  -- 1=pick, -1=reject, 0=none

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if flag ~= 1 and flag ~= -1 and flag ~= 0 then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE",
            "flag must be 1 (pick), -1 (reject), or 0 (none)"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Flag", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then
                error("Photo not found: " .. tostring(photoId))
            end
            photo:setRawMetadata("pickStatus", flag)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({
            photoId = photoId,
            flag = flag,
            message = "Flag set successfully"
        }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED",
            "Failed to set flag: " .. tostring(writeError)))
    end
end

-- Get photo flag status
function CatalogModule.getFlag(params, callback)
    ensureLrModules()
    local logger = getLogger()
    local photoId = params.photoId

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    catalog:withReadAccessDo(function()
        local photo = catalog:getPhotoByLocalId(tonumber(photoId))
        if not photo then
            callback(ErrorUtils.createError("PHOTO_NOT_FOUND",
                "Photo not found: " .. tostring(photoId)))
            return
        end

        local pickStatus = photo:getRawMetadata("pickStatus") or 0
        local label = "none"
        if pickStatus == 1 then label = "pick"
        elseif pickStatus == -1 then label = "reject"
        end

        callback(ErrorUtils.createSuccess({
            photoId = photoId,
            pickStatus = pickStatus,
            label = label
        }))
    end)
end

-- Set photo title
function CatalogModule.setTitle(params, callback)
    ensureLrModules()
    local photoId = params.photoId
    local title = params.title

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if not title then
        callback(ErrorUtils.createError("MISSING_PARAM", "title is required"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Title", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then error("Photo not found: " .. tostring(photoId)) end
            photo:setRawMetadata("title", title)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({ photoId = photoId, title = title, message = "Title set successfully" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set title: " .. tostring(writeError)))
    end
end

-- Set photo caption
function CatalogModule.setCaption(params, callback)
    ensureLrModules()
    local photoId = params.photoId
    local caption = params.caption

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if not caption then
        callback(ErrorUtils.createError("MISSING_PARAM", "caption is required"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Caption", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then error("Photo not found: " .. tostring(photoId)) end
            photo:setRawMetadata("caption", caption)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({ photoId = photoId, caption = caption, message = "Caption set successfully" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set caption: " .. tostring(writeError)))
    end
end

-- Set photo color label
function CatalogModule.setColorLabel(params, callback)
    ensureLrModules()
    local photoId = params.photoId
    local label = params.label

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "photoId is required"))
        return
    end
    if not label then
        callback(ErrorUtils.createError("MISSING_PARAM", "label is required"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Color Label", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then error("Photo not found: " .. tostring(photoId)) end
            photo:setRawMetadata("colorNameForLabel", label)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({ photoId = photoId, label = label, message = "Color label set successfully" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set color label: " .. tostring(writeError)))
    end
end

-- Apply a develop preset by name
function CatalogModule.applyDevelopPreset(params, callback)
    ensureLrModules()
    local logger = getLogger()

    if not params or not params.presetName then
        callback(ErrorUtils.createError("MISSING_PARAM", "presetName is required"))
        return
    end

    local presetName = params.presetName
    logger:debug("Applying develop preset: " .. presetName)

    -- Search for the preset by name across all folders
    local targetPreset = nil
    local folders = LrApplication.developPresetFolders()
    for _, folder in ipairs(folders) do
        local presets = folder:getDevelopPresets()
        for _, preset in ipairs(presets) do
            if preset:getName() == presetName then
                targetPreset = preset
                break
            end
        end
        if targetPreset then break end
    end

    if not targetPreset then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND",
            "Develop preset not found: " .. presetName))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end

    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Apply Develop Preset", function()
            photo:applyDevelopPreset(targetPreset)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({
            preset = presetName,
            applied = true,
            message = "Develop preset applied successfully"
        }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED",
            "Failed to apply develop preset: " .. tostring(writeError)))
    end
end

-- Create a develop snapshot
function CatalogModule.createDevelopSnapshot(params, callback)
    ensureLrModules()
    local logger = getLogger()

    if not params or not params.name then
        callback(ErrorUtils.createError("MISSING_PARAM", "name is required"))
        return
    end

    local name = params.name
    logger:debug("Creating develop snapshot: " .. name)

    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end

    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Develop Snapshot", function()
            photo:createDevelopSnapshot(name)
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({
            name = name,
            created = true,
            message = "Develop snapshot created successfully"
        }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED",
            "Failed to create develop snapshot: " .. tostring(writeError)))
    end
end

-- Copy develop settings from selected photo
function CatalogModule.copySettings(params, callback)
    ensureLrModules()
    local logger = getLogger()
    logger:debug("Copying develop settings from selected photo")

    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end

    local success, result = ErrorUtils.safeCall(function()
        photo:copySettings()
    end)

    if success then
        callback(ErrorUtils.createSuccess({
            copied = true,
            message = "Develop settings copied successfully"
        }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED",
            "Failed to copy develop settings: " .. tostring(result)))
    end
end

-- Paste develop settings to selected photo
function CatalogModule.pasteSettings(params, callback)
    ensureLrModules()
    local logger = getLogger()
    logger:debug("Pasting develop settings to selected photo")

    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end

    local writeSuccess, writeError = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Paste Develop Settings", function()
            photo:pasteSettings()
        end, { timeout = 10 })
    end)

    if writeSuccess then
        callback(ErrorUtils.createSuccess({
            pasted = true,
            message = "Develop settings pasted successfully"
        }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED",
            "Failed to paste develop settings: " .. tostring(writeError)))
    end
end

function CatalogModule.rotateLeft(params, callback)
    ensureLrModules()
    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Rotate Left", function()
            photo:rotateLeft()
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ message = "Rotated left" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.rotateRight(params, callback)
    ensureLrModules()
    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Rotate Right", function()
            photo:rotateRight()
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ message = "Rotated right" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.createVirtualCopy(params, callback)
    ensureLrModules()
    local catalog = LrApplication.activeCatalog()
    local photo = catalog:getTargetPhoto()
    if not photo then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photo selected"))
        return
    end
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Virtual Copy", function()
            photo:createVirtualCopy()
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ message = "Virtual copy created" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.setMetadata(params, callback)
    ensureLrModules()
    local photoId = params.photoId
    local key = params.key
    local value = params.value

    if not photoId then
        callback(ErrorUtils.createError("MISSING_PARAM", "Photo ID is required"))
        return
    end
    if not key then
        callback(ErrorUtils.createError("MISSING_PARAM", "Metadata key is required"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    -- Mirror the removeKeyword template: capture result/error in outer locals, wrap
    -- withWriteAccessDo in safeCall, and call back exactly once afterward. The old code
    -- invoked the callback INSIDE withWriteAccessDo with no safeCall, so a write-access
    -- timeout sent no response and the client hung to its own timeout.
    local opResult = nil
    local opError = nil
    local writeSuccess, writeErr = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Set Metadata", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then
                opError = { code = "PHOTO_NOT_FOUND", message = "Photo with ID " .. tostring(photoId) .. " not found" }
                return
            end
            photo:setRawMetadata(key, value)
            opResult = { photoId = photoId, key = key, value = value, message = "Metadata set" }
        end, { timeout = 10 })
    end)

    if opError then
        callback(ErrorUtils.createError(opError.code, opError.message))
    elseif writeSuccess and opResult then
        callback(ErrorUtils.createSuccess(opResult))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to set metadata: " .. tostring(writeErr)))
    end
end

function CatalogModule.createCollection(params, callback)
    ensureLrModules()
    local name = params.name
    if not name then
        callback(ErrorUtils.createError("MISSING_PARAM", "Collection name is required"))
        return
    end
    local returnExisting = (params.returnExisting ~= false)  -- default true
    local catalog = LrApplication.activeCatalog()
    local coll = nil
    local opError = nil
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Collection", function()
            local parent = nil
            if params.parentId then
                parent = CatalogModule._findCollectionSetById(catalog, tonumber(params.parentId))
                if not parent then
                    opError = { code = "PHOTO_NOT_FOUND", message = "Parent collection set not found: " .. tostring(params.parentId) }
                    return
                end
            end
            coll = catalog:createCollection(name, parent, returnExisting)
        end, { timeout = 10 })
    end)
    if opError then
        callback(ErrorUtils.createError(opError.code, opError.message))
        return
    end
    if not success then
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
        return
    end
    -- Read the new collection's id AFTER the write txn commits. Reading a just-created collection's
    -- info inside the same withWriteAccessDo is forbidden by the LrC SDK (live-smoke confirmed).
    local collectionId = nil
    if coll then
        ErrorUtils.safeCall(function()
            catalog:withReadAccessDo(function()
                collectionId = coll.localIdentifier
            end)
        end)
    end
    callback(ErrorUtils.createSuccess({ id = collectionId, name = name, message = "Collection created" }))
end

function CatalogModule.createSmartCollection(params, callback)
    ensureLrModules()
    local name = params.name
    if not name then
        callback(ErrorUtils.createError("MISSING_PARAM", "Smart collection name is required"))
        return
    end
    local searchDesc = params.searchDesc or {}
    local catalog = LrApplication.activeCatalog()
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Smart Collection", function()
            catalog:createSmartCollection(name, searchDesc, nil, true)
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ name = name, message = "Smart collection created" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.createCollectionSet(params, callback)
    ensureLrModules()
    local name = params.name
    if not name then
        callback(ErrorUtils.createError("MISSING_PARAM", "Collection set name is required"))
        return
    end
    local catalog = LrApplication.activeCatalog()
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Collection Set", function()
            catalog:createCollectionSet(name, nil, true)
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ name = name, message = "Collection set created" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.createKeyword(params, callback)
    ensureLrModules()
    local keyword = params.keyword
    if not keyword then
        callback(ErrorUtils.createError("MISSING_PARAM", "Keyword is required"))
        return
    end
    local catalog = LrApplication.activeCatalog()
    local success, err = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Create Keyword", function()
            catalog:createKeyword(keyword, {}, true, nil, true)
        end, { timeout = 10 })
    end)
    if success then
        callback(ErrorUtils.createSuccess({ keyword = keyword, message = "Keyword created" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.removeKeyword(params, callback)
    ensureLrModules()
    local photoId = params.photoId
    local keyword = params.keyword
    if not photoId or not keyword then
        callback(ErrorUtils.createError("MISSING_PARAM", "Photo ID and keyword are required"))
        return
    end
    local catalog = LrApplication.activeCatalog()
    local opResult = nil
    local opError = nil
    local writeSuccess, writeErr = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo("Remove Keyword", function()
            local photo = catalog:getPhotoByLocalId(tonumber(photoId))
            if not photo then
                opError = { code = "PHOTO_NOT_FOUND", message = "Photo not found" }
                return
            end
            -- Find keyword object by name
            local keywords = photo:getRawMetadata("keywords")
            local keywordObj = nil
            if keywords then
                for _, kw in ipairs(keywords) do
                    if kw:getName() == keyword then
                        keywordObj = kw
                        break
                    end
                end
            end
            if not keywordObj then
                opError = { code = "KEYWORD_NOT_FOUND", message = "Keyword '" .. keyword .. "' not found on this photo" }
                return
            end
            photo:removeKeyword(keywordObj)
            opResult = { photoId = photoId, keyword = keyword, message = "Keyword removed" }
        end, { timeout = 10 })
    end)

    if opError then
        callback(ErrorUtils.createError(opError.code, opError.message))
    elseif writeSuccess and opResult then
        callback(ErrorUtils.createSuccess(opResult))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(writeErr)))
    end
end

-- Pure: find a collection by localIdentifier among all collections (incl. nested in sets). Unit-testable.
function CatalogModule._findCollectionById(node, collectionId)
    if collectionId == nil then return nil end
    for _, c in ipairs(CatalogModule._collectAllCollections(node)) do
        if c.localIdentifier == collectionId then return c end
    end
    return nil
end

-- Pure: recursively collect every collection SET (descending through nested sets). Unit-testable.
function CatalogModule._collectAllCollectionSets(node)
    local result = {}
    if node == nil then return result end
    local function visit(n)
        if n.getChildCollectionSets then
            for _, s in ipairs(n:getChildCollectionSets()) do
                table.insert(result, s)
                visit(s)
            end
        end
    end
    visit(node)
    return result
end

-- Pure: find a collection SET by localIdentifier. Unit-testable.
function CatalogModule._findCollectionSetById(node, setId)
    if setId == nil then return nil end
    for _, s in ipairs(CatalogModule._collectAllCollectionSets(node)) do
        if s.localIdentifier == setId then return s end
    end
    return nil
end

-- Pure: map CLI params -> Lightroom LR_* export settings. Unit-testable (no SDK calls).
-- ORIGINAL/DNG are passthrough/raw (no re-encode). Resize applies to raster formats; the JPEG quality
-- knob applies to JPEG only. Gating on a raster allow-list (not "~= ORIGINAL") keeps DNG from getting
-- jpeg_quality/resize it can't use. [SDK-VERIFY] every LR_* key against live LrC.
function CatalogModule._buildExportSettings(params)
    local format = params.format or "ORIGINAL"
    local RASTER = { JPEG = true, TIFF = true, PNG = true, PSD = true }
    local settings = {
        LR_export_destinationType = "specificFolder",
        LR_export_destinationPathPrefix = params.dest,
        LR_export_useSubfolder = false,
        LR_format = format,
        LR_reimportExportedPhoto = false,  -- keep exports OUT of the catalog (auto-XMP pipeline)
        LR_collisionHandling = params.overwrite or "rename",
    }
    if RASTER[format] then
        if format == "JPEG" and params.quality ~= nil then
            settings.LR_jpeg_quality = tonumber(params.quality) / 100  -- [SDK-VERIFY] 0..1 scale
        end
        if params.resizeLongEdge ~= nil then
            settings.LR_size_doConstrain = true
            settings.LR_size_resizeType = "longEdge"
            settings.LR_size_maxHeight = tonumber(params.resizeLongEdge)
            settings.LR_size_maxWidth = tonumber(params.resizeLongEdge)
            settings.LR_size_units = "pixels"
        else
            settings.LR_size_doConstrain = false
        end
    end
    return settings
end

-- Export photos to disk via LrExportSession. Default ORIGINAL passthrough; partial-success per photo.
-- Single callback always reached. Photo resolution under read access; render loop polls shouldAbort.
function CatalogModule.exportPhotos(params, callback)
    ensureLrModules()
    params = params or {}
    local dest = params.dest
    if not dest or dest == "" then
        callback(ErrorUtils.createError("MISSING_PARAM", "dest is required"))
        return
    end
    if not LrFileUtils.exists(dest) then  -- [SDK-VERIFY] fail-fast, no auto-mkdir
        callback(ErrorUtils.createError("DEST_NOT_FOUND", "Destination folder not found: " .. tostring(dest)))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local photos, notFound = {}, {}
    local resolveOk, resolveErr = ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            if params.photoIds and type(params.photoIds) == "table" and #params.photoIds > 0 then
                for _, pid in ipairs(params.photoIds) do
                    local p = catalog:getPhotoByLocalId(tonumber(pid))
                    if p then table.insert(photos, p) else table.insert(notFound, tostring(pid)) end
                end
            else
                -- Selection fallback via the shared filmstrip-guard helper: nil target photo =>
                -- empty (never the whole filmstrip). Same guard as getSelectedPhotos.
                photos = CatalogModule._resolveSelection(catalog:getTargetPhoto(), catalog:getTargetPhotos())
            end
        end)
    end)
    if not resolveOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to resolve photos: " .. tostring(resolveErr)))
        return
    end
    if #photos == 0 then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photos to export (empty selection and no valid photoIds)"))
        return
    end

    local exportSettings = CatalogModule._buildExportSettings(params)
    local requestId = params._requestId
    local command = params._command or "catalog.exportPhotos"
    local router = getCommandRouter()
    local continueOnError = params.continueOnError
    if continueOnError == nil then continueOnError = true end

    local results, exported, failed, incomplete = {}, 0, 0, false
    local processed = {}
    local renderOk, renderErr = ErrorUtils.safeCall(function()
        local session = LrExportSession({  -- [SDK-VERIFY] constructor signature
            photosToExport = photos,
            exportSettings = exportSettings,
        })
        for _, rendition in session:renditions() do  -- [SDK-VERIFY] canonical LrExportSession iterator
            if router and requestId and router:shouldAbort(requestId, command) then
                incomplete = true
                break
            end
            if rendition and rendition.photo then  -- defensive: skip a malformed rendition, don't crash the batch
                local pid = tostring(rendition.photo.localIdentifier)
                processed[pid] = true
                local ok, pathOrMessage = rendition:waitForRender()  -- [SDK-VERIFY] (success, pathOrMessage)
                if ok then
                    exported = exported + 1
                    table.insert(results, { photoId = pid, outputPath = pathOrMessage, success = true })
                else
                    failed = failed + 1
                    table.insert(results, { photoId = pid, outputPath = nil, success = false, error = tostring(pathOrMessage) })
                    if not continueOnError then incomplete = true; break end
                end
                LrTasks.yield()
            end
        end
    end)
    if not renderOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Export session failed: " .. tostring(renderErr)))
        return
    end

    -- Resolved photos that were never rendered (aborted, stopped-on-error, or a malformed rendition) are
    -- reported as failed rows so the accounting reflects every requested photo, not just the ones attempted.
    for _, photo in ipairs(photos) do
        local pid = tostring(photo.localIdentifier)
        if not processed[pid] then
            failed = failed + 1
            table.insert(results, { photoId = pid, outputPath = nil, success = false,
                error = incomplete and "Not rendered (export stopped early)" or "Not rendered" })
        end
    end

    -- Photo IDs that never resolved to a catalog photo are reported as failed rows (honest count)
    for _, pid in ipairs(notFound) do
        failed = failed + 1
        table.insert(results, { photoId = pid, outputPath = nil, success = false, error = "Photo not found" })
    end

    callback(ErrorUtils.createSuccess({
        dest = dest,
        format = params.format or "ORIGINAL",
        results = results,
        exported = exported,
        failed = failed,
        total = #results,
        incomplete = incomplete,
    }))
end

-- Shared core for add/remove collection membership. Mirrors removeKeyword's callback-once template.
function CatalogModule._mutateCollectionMembership(params, callback, verb, actionName)
    ensureLrModules()
    params = params or {}
    if params.collectionId == nil then
        callback(ErrorUtils.createError("MISSING_PARAM", "collectionId is required"))
        return
    end
    local collectionId = tonumber(params.collectionId)
    if not collectionId then
        callback(ErrorUtils.createError("INVALID_PARAM", "collectionId must be a number"))
        return
    end
    local photoIds = params.photoIds
    if type(photoIds) ~= "table" or #photoIds == 0 then
        callback(ErrorUtils.createError("INVALID_PARAM_VALUE", "photoIds must be a non-empty array"))
        return
    end

    local catalog = LrApplication.activeCatalog()
    local collection, collectionName = nil, nil
    local photos, notFound = {}, {}
    local mutable = false

    -- 1. Resolve the collection + photos under READ access. Resolving/reading collection info must NOT
    -- share the withWriteAccessDo that mutates it -- the LrC SDK forbids same-txn read-after-write.
    local resolveOk, resolveErr = ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            collection = CatalogModule._findCollectionById(catalog, collectionId)
            if collection then
                collectionName = collection:getName()
                mutable = type(collection.addPhotos) == "function" and type(collection.removePhotos) == "function"
                for _, pid in ipairs(photoIds) do
                    local p = catalog:getPhotoByLocalId(tonumber(pid))
                    if p then table.insert(photos, p) else table.insert(notFound, tostring(pid)) end
                end
            end
        end)
    end)
    if not resolveOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to resolve collection: " .. tostring(resolveErr)))
        return
    end
    if not collection then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "Collection not found: " .. tostring(collectionId)))
        return
    end
    if not mutable then
        callback(ErrorUtils.createError("NOT_SUPPORTED", "Collection does not support membership changes (smart collection?)"))
        return
    end
    if #photos == 0 then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND", "No photos found with the provided IDs"))
        return
    end

    -- 2. Mutate membership under WRITE access.
    local writeOk, writeErr = ErrorUtils.safeCall(function()
        catalog:withWriteAccessDo(actionName, function()
            if verb == "add" then
                collection:addPhotos(photos)  -- [SDK-VERIFY]
            else
                collection:removePhotos(photos)  -- [SDK-VERIFY]
            end
        end, { timeout = 10 })
    end)
    if not writeOk then
        callback(ErrorUtils.createError("OPERATION_FAILED", "Failed to update collection membership: " .. tostring(writeErr)))
        return
    end

    -- 3. Read the post-commit membership count under READ access (separate txn -> accurate count).
    local photoCount = nil
    ErrorUtils.safeCall(function()
        catalog:withReadAccessDo(function()
            photoCount = #collection:getPhotos()
        end)
    end)

    callback(ErrorUtils.createSuccess({
        collectionId = collectionId,
        collectionName = collectionName,
        photoCount = photoCount,
        requested = #photoIds,
        affected = #photos,
        notFound = (#notFound > 0) and notFound or nil,
    }))
end

function CatalogModule.addPhotosToCollection(params, callback)
    CatalogModule._mutateCollectionMembership(params, callback, "add", "Add Photos to Collection")
end

function CatalogModule.removePhotosFromCollection(params, callback)
    CatalogModule._mutateCollectionMembership(params, callback, "remove", "Remove Photos from Collection")
end

function CatalogModule.setViewFilter(params, callback)
    ensureLrModules()
    local filter = params.filter or {}
    local catalog = LrApplication.activeCatalog()
    local success, err = ErrorUtils.safeCall(function()
        catalog:setViewFilter(filter)
    end)
    if success then
        callback(ErrorUtils.createSuccess({ message = "View filter set" }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(err)))
    end
end

function CatalogModule.getCurrentViewFilter(params, callback)
    ensureLrModules()
    local catalog = LrApplication.activeCatalog()
    local success, result = ErrorUtils.safeCall(function()
        return catalog:getCurrentViewFilter()
    end)
    if success then
        callback(ErrorUtils.createSuccess({ filter = result }))
    else
        callback(ErrorUtils.createError("OPERATION_FAILED", tostring(result)))
    end
end

function CatalogModule.removeFromCatalog(params, callback)
    -- The Lightroom Classic SDK provides no API to remove a photo from the
    -- catalog: LrCatalog has no removePhoto/removePhotos method -- removal is a
    -- UI-only action (Photo > Remove Photo from Catalog). The previous code
    -- called catalog:removePhoto(photo), a nil method, so this verb always
    -- failed with a cryptic OPERATION_FAILED (caught by safeCall). Short-circuit
    -- with an honest capability error instead of entering a write transaction
    -- for an operation that can never succeed.
    -- Source: lr CLI bridge Lua bug audit, 2026-06-12.
    local photoId = params and params.photoId
    if not photoId then
        callback(ErrorUtils.createError(ErrorUtils.CODES.MISSING_PARAM, "Photo ID is required"))
        return
    end
    callback(ErrorUtils.createError(
        ErrorUtils.CODES.NOT_SUPPORTED,
        "Removing a photo from the catalog is not supported by the Lightroom SDK. "
        .. "Remove it manually in Lightroom (Photo > Remove Photo from Catalog)."
    ))
end

-- Get photos from a specific collection by ID
function CatalogModule.getCollectionPhotos(params, callback)
    ensureLrModules()
    local logger = getLogger()

    if not params or not params.collectionId then
        callback(ErrorUtils.createError("MISSING_PARAM", "collectionId is required"))
        return
    end

    local collectionId = tonumber(params.collectionId)
    if not collectionId then
        callback(ErrorUtils.createError("INVALID_PARAM", "collectionId must be a number"))
        return
    end

    local limit = params.limit or DEFAULT_PAGE_SIZE
    local offset = math.max(params.offset or 0, 0)

    logger:debug("Getting photos from collection: " .. tostring(collectionId))

    local catalog = LrApplication.activeCatalog()

    -- Find the collection by ID
    local targetCollection = nil
    catalog:withReadAccessDo(function()
        for _, collection in ipairs(CatalogModule._collectAllCollections(catalog)) do
            if collection.localIdentifier == collectionId then
                targetCollection = collection
                break
            end
        end
    end)

    if not targetCollection then
        callback(ErrorUtils.createError("PHOTO_NOT_FOUND",
            "Collection not found: " .. tostring(collectionId)))
        return
    end

    -- Get photos from the collection
    local allPhotos
    catalog:withReadAccessDo(function()
        allPhotos = targetCollection:getPhotos()
    end)

    local total = #allPhotos

    -- Apply pagination
    local startIdx = offset + 1
    local endIdx = math.min(startIdx + limit - 1, total)
    local resultPhotos = {}

    local CHUNK_SIZE = METADATA_CHUNK_SIZE
    for chunkStart = startIdx, endIdx, CHUNK_SIZE do
        local chunkEnd = math.min(chunkStart + CHUNK_SIZE - 1, endIdx)
        catalog:withReadAccessDo(function()
            for i = chunkStart, chunkEnd do
                local photo = allPhotos[i]
                table.insert(resultPhotos, {
                    id = photo.localIdentifier,
                    uuid = photo:getRawMetadata("uuid"),
                    filename = photo:getFormattedMetadata("fileName"),
                    rating = photo:getRawMetadata("rating"),
                    colorLabel = photo:getRawMetadata("colorNameForLabel"),
                })
            end
        end)
        LrTasks.yield()
    end

    callback(ErrorUtils.createSuccess({
        photos = resultPhotos,
        total = total,
        returned = #resultPhotos,
        offset = offset,
        limit = limit,
        collectionId = collectionId,
        collectionName = targetCollection:getName(),
    }))
end

-- Get develop presets (list/search)
function CatalogModule.getDevelopPresets(params, callback)
    ensureLrModules()
    local logger = getLogger()

    local searchQuery = params and params.query or nil
    logger:debug("Getting develop presets" .. (searchQuery and (", query: " .. searchQuery) or ""))

    local folders = LrApplication.developPresetFolders()
    local resultPresets = {}

    for _, folder in ipairs(folders) do
        local folderName = folder:getName()
        local presets = folder:getDevelopPresets()
        for _, preset in ipairs(presets) do
            local presetName = preset:getName()
            local include = true
            if searchQuery then
                -- Case-insensitive substring match on name or folder
                local lowerQuery = string.lower(searchQuery)
                include = string.find(string.lower(presetName), lowerQuery, 1, true) ~= nil
                    or string.find(string.lower(folderName), lowerQuery, 1, true) ~= nil
            end
            if include then
                table.insert(resultPresets, {
                    name = presetName,
                    folder = folderName,
                })
            end
        end
        LrTasks.yield()
    end

    callback(ErrorUtils.createSuccess({
        presets = resultPresets,
        count = #resultPresets,
    }))
end

return CatalogModule
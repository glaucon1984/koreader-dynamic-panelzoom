--[[
PanelData - loads pre-authored panel data ("panels.json") for a comic.

When a comic was converted from a Kindle KFX book with kfx2cbz
(https://github.com/tarcisiotm/koreader-dynamic-panelzoom, tools/kfx2cbz) the
publisher's panel rectangles and reading order are stored in a small JSON
file.  This module finds and parses that file so main.lua can use the exact
panels instead of guessing them with Leptonica.

Lookup order (first hit wins):
  1. <document>.panels.json            e.g. book.cbz.panels.json
  2. <document without ext>.panels.json e.g. book.panels.json
  3. panels.json inside the archive     (cbz / zip / cbt / cbr ...)

File format ("comic-panels", version 1):
  {
    "format": "comic-panels", "version": 1,
    "reading_direction": "ltr" | "rtl",
    "pages": [
      { "index": 1, "file": "0001.jpg", "width": 1344, "height": 1920,
        "panels": [ {"order": 1, "x": 0.07, "y": 0.05, "w": 0.48, "h": 0.31}, ... ] }
    ]
  }
  x, y, w, h are fractions (0..1) of the page image; index is the 1-based page
  number of the document.
]]

local logger = require("logger")
local json = require("json")

local PanelData = {}

PanelData.FORMAT = "comic-panels"
PanelData.FILE_NAME = "panels.json"
PanelData.ARCHIVE_EXTS = {
    cbz = true, zip = true, cbt = true, tar = true, cbr = true, rar = true, cb7 = true,
}

local function fileExists(path)
    local f = io.open(path, "rb")
    if f then
        f:close()
        return true
    end
    return false
end

local function readFile(path)
    local f = io.open(path, "rb")
    if not f then return nil end
    local content = f:read("*all")
    f:close()
    return content
end

local function fileExt(path)
    return (path:match("%.([^./\\]+)$") or ""):lower()
end

local function baseName(path)
    return path:match("([^/\\]+)$") or path
end

-- Candidate sidecar paths for a document.
function PanelData.sidecarPaths(doc_path)
    local paths = { doc_path .. ".panels.json" }
    local stem = doc_path:match("^(.*)%.[^./\\]+$")
    if stem and stem ~= "" then
        table.insert(paths, stem .. ".panels.json")
    end
    return paths
end

-- Read FILE_NAME from inside an archive (cbz, ...). Returns content, entry path.
function PanelData.readFromArchive(doc_path)
    local ok, Archiver = pcall(require, "ffi/archiver")
    if not ok or not Archiver or not Archiver.Reader then
        logger.dbg("PanelData: ffi/archiver not available")
        return nil
    end
    local reader = Archiver.Reader:new()
    if not reader:open(doc_path) then
        return nil
    end
    -- First matching entry wins (kfx2cbz writes it at the archive root). We
    -- break right away so the reader is still positioned on that entry and
    -- extractToMemory() does not need to rewind the archive.
    local found
    for entry in reader:iterate() do
        if entry.mode == "file" and baseName(entry.path):lower() == PanelData.FILE_NAME then
            found = entry
            break
        end
    end
    local content
    if found then
        content = reader:extractToMemory(found.path)
        if not content and reader.err then
            logger.warn("PanelData: could not read", found.path, "from", doc_path, ":", reader.err)
        end
    end
    reader:close()
    if content then
        return content, "archive:" .. found.path
    end
    return nil
end

local function toNumber(v)
    if type(v) == "number" then return v end
    if type(v) == "string" then return tonumber(v) end
    return nil
end

local function parseRect(p)
    local x, y, w, h = toNumber(p.x), toNumber(p.y), toNumber(p.w), toNumber(p.h)
    if not (x and y and w and h) then return nil end
    if w <= 0 or h <= 0 then return nil end
    -- clamp to the page
    x = math.max(0, math.min(1, x))
    y = math.max(0, math.min(1, y))
    w = math.max(0, math.min(1 - x, w))
    h = math.max(0, math.min(1 - y, h))
    if w <= 0 or h <= 0 then return nil end
    return { x = x, y = y, w = w, h = h }
end

-- Parse a JSON string into the internal structure:
-- { pages = { [pageno] = { panels... } }, reading_direction, page_count, panel_count, source }
function PanelData.parse(content, source)
    local ok, data = pcall(json.decode, content)
    if not ok or type(data) ~= "table" then
        logger.warn("PanelData: invalid JSON in", source)
        return nil
    end
    if data.format and data.format ~= PanelData.FORMAT then
        logger.warn("PanelData: unknown format", data.format, "in", source)
        return nil
    end
    if type(data.pages) ~= "table" then
        logger.warn("PanelData: no pages array in", source)
        return nil
    end

    local result = {
        source = source,
        reading_direction = (data.reading_direction == "rtl") and "rtl" or (data.reading_direction == "ltr" and "ltr" or nil),
        title = type(data.source) == "table" and data.source.title or nil,
        pages = {},
        page_count = 0,
        panel_count = 0,
    }

    local implicit_index = 0
    for _, page in ipairs(data.pages) do
        implicit_index = implicit_index + 1
        if type(page) == "table" then
            local index = toNumber(page.index) or implicit_index
            index = math.floor(index)
            local panels = {}
            for _, p in ipairs(page.panels or {}) do
                if type(p) == "table" then
                    local rect = parseRect(p)
                    if rect then
                        rect.order = toNumber(p.order) or (#panels + 1)
                        local view = type(p.view) == "table" and parseRect(p.view) or nil
                        if view then rect.view = view end
                        table.insert(panels, rect)
                    end
                end
            end
            table.sort(panels, function(a, b) return a.order < b.order end)
            for i, p in ipairs(panels) do p.order = i end
            if index >= 1 then
                result.pages[index] = panels
                result.page_count = result.page_count + 1
                result.panel_count = result.panel_count + #panels
            end
        end
    end

    if result.page_count == 0 then
        logger.warn("PanelData: no usable pages in", source)
        return nil
    end
    return result
end

-- Load panel data for a document. Returns the parsed structure or nil.
function PanelData.load(doc_path)
    if not doc_path then return nil end

    for _, path in ipairs(PanelData.sidecarPaths(doc_path)) do
        if fileExists(path) then
            local content = readFile(path)
            if content then
                local data = PanelData.parse(content, path)
                if data then
                    logger.info("PanelData: loaded sidecar", path)
                    return data
                end
            end
        end
    end

    if PanelData.ARCHIVE_EXTS[fileExt(doc_path)] then
        local content, source = PanelData.readFromArchive(doc_path)
        if content then
            local data = PanelData.parse(content, source)
            if data then
                logger.info("PanelData: loaded", source, "from", doc_path)
                return data
            end
        end
    end

    return nil
end

-- Panels for a page (1-based). Returns a *copy* of the list, or nil when the
-- data does not describe that page at all.
function PanelData.getPanels(data, pageno)
    if not data or not pageno then return nil end
    local panels = data.pages[pageno]
    if not panels then return nil end
    local copy = {}
    for i, p in ipairs(panels) do
        copy[i] = { x = p.x, y = p.y, w = p.w, h = p.h, order = p.order, view = p.view }
    end
    return copy
end

function PanelData.hasPage(data, pageno)
    return data ~= nil and pageno ~= nil and data.pages[pageno] ~= nil
end

return PanelData

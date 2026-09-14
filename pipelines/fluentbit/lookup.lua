-- The bundled lookup fixture has unquoted ipv4,region,env columns.
-- Read once at startup, outside the timed per-event callback.
local locations = {}
local file = assert(io.open("/tmp/lookup-benchmark.csv", "r"))
assert(file:read("*l"):gsub("\r$", "") == "ipv4,region,env", "Unexpected CSV header")
for line in file:lines() do
    local ip, region, env = line:match("^([^,]+),([^,]+),([^,\r]+)\r?$")
    assert(ip, "Malformed lookup CSV row")
    locations[ip] = {region, env}
end
file:close()

function enrich(tag, timestamp, record)
    local pii = record["pii"]
    local row = type(pii) == "table" and locations[pii["ipv4"]] or nil
    record["region"] = row and row[1] or "Unknown"
    record["env"] = row and row[2] or "Unknown"
    return 2, timestamp, record
end

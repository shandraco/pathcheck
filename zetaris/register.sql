-- Register PathCheck's four sources in Zetaris (run once, as the Zetaris administrator).
-- Each source is a separate REST endpoint, so Zetaris is the one place they are joined.
-- scripts/zetaris_setup.py runs these statements one at a time and checks the row counts.
CREATE LIGHTNING DATABASE pathcheck DESCRIBE BY "PathCheck: WSU catalog, schedule, programs, policies"
CREATE LIGHTNING REST TABLE courses FROM pathcheck REQUEST (endpoint "https://raw.githubusercontent.com/shandraco/pathcheck/main/data/courses.json", method "GET", http_encoding "URLENCODED", response_type "JSON", insecure_ssl "false") HEADER () BODY ()
CREATE LIGHTNING REST TABLE sections FROM pathcheck REQUEST (endpoint "https://raw.githubusercontent.com/shandraco/pathcheck/main/data/sections.json", method "GET", http_encoding "URLENCODED", response_type "JSON", insecure_ssl "false") HEADER () BODY ()
CREATE LIGHTNING REST TABLE programs FROM pathcheck REQUEST (endpoint "https://raw.githubusercontent.com/shandraco/pathcheck/main/data/programs.json", method "GET", http_encoding "URLENCODED", response_type "JSON", insecure_ssl "false") HEADER () BODY ()
CREATE LIGHTNING REST TABLE policies FROM pathcheck REQUEST (endpoint "https://raw.githubusercontent.com/shandraco/pathcheck/main/data/policies.json", method "GET", http_encoding "URLENCODED", response_type "JSON", insecure_ssl "false") HEADER () BODY ()

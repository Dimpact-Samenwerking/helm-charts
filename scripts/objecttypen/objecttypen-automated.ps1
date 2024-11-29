# Define API host and API key
$objecttypes_host = "https://ontw-objecttypen.sschosting.nl"
$api_key = "api-key"

# Define the object types and their JSON URLs
$objectTypes = @(
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/Medewerker/medewerker-schema.json"; name_plural = "Medewerkers" },
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/Afdeling%20en%20Groep/afdeling-schema.json"; name_plural = "Afdelingen" },
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/Afdeling%20en%20Groep/groep-schema.json"; name_plural = "Groepen" },
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/Interne%20taak/internetaak-schema.json"; name_plural = "InterneTaken" },
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/PDC%20-%20kennisartikel/kennisartikel-schema.json"; name_plural = "Kennisartikelen" },
    @{ url = "https://raw.githubusercontent.com/open-objecten/objecttypes/refs/heads/main/community-concepts/VAC/vac-schema.json"; name_plural = "VAC's" }
)

# Function to make an API request
function Invoke-ApiRequest {
    param (
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers,
        [string]$Body = $null
    )
    $response = Invoke-RestMethod -Method $Method -Uri $Url -Headers $Headers -Body $Body
    return $response
}

# Set headers for API calls
$headers = @{
    "Content-Type" = "application/json"
    "Authorization" = "Token $api_key"
}
$headersWebRequest = @{
    "Content-Type" = "application/json"
    "Authorization" = "Token $api_key"
    "Transfer-Encoding" = "chunked"

}
# Iterate over each object type
foreach ($objectType in $objectTypes) {
    # Fetch JSON schema from the URL
    Write-Host "Fetching JSON schema for $($objectType.name_plural)..."
    $response = Invoke-WebRequest -Uri $objectType.url
    $jsonSchema = $response.Content

    # Create object type
    $createBody = @"
{
    `"name`": `"$($objectType.name_plural)`",
    `"namePlural`": `"$($objectType.name_plural)`",
    `"description`": `"Automatically created object type for $($objectType.name_plural).`",
    `"dataClassification`": `"open`"
}
"@

    Write-Host "Creating object type $($objectType.name_plural)..."
    $createResponse = Invoke-WebRequest -Method "POST" -Uri "$objecttypes_host/api/v2/objecttypes" -Headers $headers -Body $createBody
    $objecttype_uuid = ($createResponse.Content | ConvertFrom-Json).uuid
    $objectType.uuid = $objecttype_uuid
    # Create object type version
    $versionBody = @"
{
    `"status`": `"draft`",
    `"jsonSchema`": $([System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::UTF8.GetBytes($jsonSchema)))
}
"@
try {
    $validatedJson = $versionBody | ConvertFrom-Json | ConvertTo-Json -Depth 100
    Write-Host "JSON is valid."
} catch {
    Write-Host "Invalid JSON detected. Error: $($_.Exception.Message)"
    return
}


    Write-Host "Creating version for object type $($objectType.name_plural)..."
    Start-Sleep -Milliseconds 1500  # Small delay to ensure processing
    # Write-Host "Body: `n $versionBody"
    $versionResponse = Invoke-WebRequest -Method "POST" -Uri "$objecttypes_host/api/v2/objecttypes/$objecttype_uuid/versions" -Headers $headersWebRequest -Body $versionBody
    $version_id = ($versionResponse.Content | ConvertFrom-Json).version

    # Publish object type version
    $publishBody = @"
{
    `"status`": `"published`"
}
"@

    Write-Host "Publishing version $version_id for object type $($objectType.name_plural)..."
    Start-Sleep -Milliseconds 1500  # Small delay to ensure processing
    $publishResponse = Invoke-WebRequest -Method "PATCH" -Uri "$objecttypes_host/api/v2/objecttypes/$objecttype_uuid/versions/$version_id" -Headers $headers -Body $publishBody
    $publishResponse.Content | ConvertFrom-Json
    Write-Host "Completed processing for $($objectType.name_plural).`n"
}

Write-Host "All object types processed successfully.`n`n"
Write-Host "### HELM VALUES ###`n"
foreach ($objectType in $objectTypes) {
    Write-Host "$($objectType.name_plural) UUID: $($objectType.uuid)"
}
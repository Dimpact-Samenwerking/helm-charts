# Load configurations from an input file
$configFilePath = "./podiumd-contact-config.json"
if (-Not (Test-Path $configFilePath)) {
    Write-Error "Configuration file not found at path: $configFilePath"
    exit
}

$config = Get-Content -Path $configFilePath | ConvertFrom-Json

# Initialize variables from configuration
$baseUrl = $config.baseUrl
$loginUrl = "$baseUrl$($config.loginEndpoint)"
$username = $config.username
$password = $config.password
$requests = $config.requests

# Initialize web session
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$globalOutputs = @{} # Store outputs for dynamic references

# Function to extract CSRF token from HTML content
function Get-CsrfToken {
    param (
        [string]$content
    )
    $csrfTokenPattern = 'name="csrfmiddlewaretoken" value="([^"]+)"'
    return [regex]::Match($content, $csrfTokenPattern).Groups[1].Value
}

# Function to make GET requests with common headers
function Get-Request {
    param (
        [string]$uri,
        [Microsoft.PowerShell.Commands.WebRequestSession]$session
    )
    return Invoke-WebRequest -Uri $uri -WebSession $session -UseBasicParsing -Headers @{
        "ngrok-skip-browser-warning" = "true"
    }
}

# Function to make POST requests with common headers
function Post-Request {
    param (
        [string]$uri,
        [string]$body,
        [Microsoft.PowerShell.Commands.WebRequestSession]$session,
        [string]$contentType = "application/x-www-form-urlencoded",
        [hashtable]$additionalHeaders = @{}
    )

    $headers = @{
        "ngrok-skip-browser-warning" = "true"
        "Referer" = $uri
    }
    $headers += $additionalHeaders

    return Invoke-WebRequest -Uri $uri -Method POST -Body $body -WebSession $session -ContentType $contentType -UseBasicParsing -Headers $headers
}

# Function to convert hashtable to URL-encoded form data string
function ConvertTo-FormDataString {
    param (
        [hashtable]$data
    )
    return ($data.GetEnumerator() | ForEach-Object {
        [System.Uri]::EscapeDataString($_.Key) + "=" + [System.Uri]::EscapeDataString($_.Value)
    }) -join "&"
}

# Function to replace dynamic placeholders in formFields
function Resolve-FormFields {
    param (
        [hashtable]$formFields,
        [hashtable]$globalOutputs
    )

    # Create a new hashtable to store the resolved form fields
    $resolvedFields = @{}

    foreach ($key in $formFields.Keys) {
        $value = $formFields[$key]
        if ($value -is [string] -and $value.StartsWith("$")) {
            $resolvedKey = $value.TrimStart('$')
            if ($globalOutputs.ContainsKey($resolvedKey)) {
                # Use the value from globalOutputs
                $resolvedFields[$key] = $globalOutputs[$resolvedKey]
            } else {
                # Keep the unresolved value if not found in globalOutputs
                $resolvedFields[$key] = $value
            }
        } else {
            # Copy the original value if it's not a dynamic reference
            $resolvedFields[$key] = $value
        }
    }

    return $resolvedFields
}

# Function to extract specific data from response content
function Extract-Value {
    param (
        [string]$content,
        [string]$pattern
    )
    if ([string]::IsNullOrWhiteSpace($pattern)) {
        return $null
    }
    $match = [regex]::Match($content, $pattern)
    if ($match.Success) {
        return $match.Groups[1].Value
    }
    return $null
}

# Function to execute requests recursively
function Execute-Request {
    param (
        [hashtable]$requestConfig,
        [Microsoft.PowerShell.Commands.WebRequestSession]$session
    )

    $relativeUrl = $requestConfig.url
    $url = if ($relativeUrl -match "^https?://") {
        $relativeUrl
    } else {
        "$baseUrl$relativeUrl"
    }

    $formFields = $requestConfig.formFields
    $outputKey = $requestConfig.output_key
    $extractPattern = $requestConfig.extractPattern

    # Convert formFields to Hashtable if it is a PSCustomObject
    if ($formFields -is [PSCustomObject]) {
        $formFieldsHashtable = @{}
        foreach ($key in $formFields.PSObject.Properties.Name) {
            $formFieldsHashtable[$key] = $formFields.$key
        }
        $formFields = $formFieldsHashtable
    }

    # Resolve dynamic values in formFields
    $formFields = Resolve-FormFields -formFields $formFields -globalOutputs $globalOutputs

    Write-Progress -Activity "Processing Request" -Status "Fetching CSRF token..."
    $response = Get-Request -uri $url -session $session
    $formCsrfToken = Get-CsrfToken -content $response.Content

    # Add CSRF token to formFields
    $formFields["csrfmiddlewaretoken"] = $formCsrfToken
    $bodyString = ConvertTo-FormDataString -data $formFields

    Write-Progress -Activity "Processing Request" -Status "Submitting form..."
    $response = Post-Request -uri $url -body $bodyString -session $session

    # Extract output using pattern if provided
    if ($extractPattern) {
        $extractedValue = Extract-Value -content $response.Content -pattern $extractPattern
        if ($outputKey) {
            $globalOutputs[$outputKey] = $extractedValue
        }
    }

    # Process child requests
    if ($requestConfig.children) {
        foreach ($childRequest in $requestConfig.children) {
            # Convert childRequest from PSCustomObject to Hashtable
            $childRequestHashtable = @{}
            foreach ($key in $childRequest.PSObject.Properties.Name) {
                $childRequestHashtable[$key] = $childRequest.$key
            }
            Execute-Request -requestConfig $childRequestHashtable -session $session
        }
    }
}

# Perform login
function Login {
    param (
        [string]$loginUrl,
        [string]$username,
        [string]$password,
        [Microsoft.PowerShell.Commands.WebRequestSession]$session
    )

    Write-Progress -Activity "Login Process" -Status "Fetching CSRF token..."
    # Step 1: Get initial CSRF token
    $response = Get-Request -uri $loginUrl -session $session
    $formCsrfToken = Get-CsrfToken -content $response.Content

    Write-Progress -Activity "Login Process" -Status "Submitting credentials..."
    # Step 2: Submit login form
    $loginBody = @{
        "csrfmiddlewaretoken" = $formCsrfToken
        "admin_login_view-current_step" = "auth"
        "auth-username" = $username
        "auth-password" = $password
        "next" = "/admin/"
    }
    $response = Post-Request -uri $loginUrl -body (ConvertTo-FormDataString $loginBody) -session $session

    # Check if login was successful
    if ($response.Content.Contains("Logged in as")) {
        Write-Host "Logged in successfully."
        return $true
    }

    Write-Progress -Activity "Login Process" -Status "Checking for 2FA requirement..."
    # Check if 2FA is required
    if ($response.Content -match 'name="token-otp_token"') {
        # Step 3: Get CSRF token for 2FA
        $formCsrfToken2 = Get-CsrfToken -content $response.Content

        # Step 4: Prompt for 2FA code
        $otpCode = Read-Host -Prompt "Enter your 2FA code"

        Write-Progress -Activity "Login Process" -Status "Submitting 2FA code..."
        $twoFactorBody = @{
            "csrfmiddlewaretoken" = $formCsrfToken2
            "admin_login_view-current_step" = "token"
            "token-otp_token" = $otpCode
        }
        $response2 = Post-Request -uri $loginUrl -body (ConvertTo-FormDataString $twoFactorBody) -session $session

        if ($response2.Content.Contains("Logged in as")) {
            Write-Host "Logged in successfully with 2FA."
            return $true
        } else {
            Write-Host "2FA verification failed."
            return $false
        }
    } else {
        Write-Host "Login failed."
        return $false
    }
}

# Main script execution
if (Login -loginUrl $loginUrl -username $username -password $password -session $session) {
    foreach ($request in $requests) {
        # Convert PSCustomObject to Hashtable
        $requestHashtable = @{}
        foreach ($key in $request.PSObject.Properties.Name) {
            $requestHashtable[$key] = $request.$key
        }
    
        Execute-Request -requestConfig $requestHashtable -session $session
    }
}

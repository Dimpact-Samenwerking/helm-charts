# 🔐 ITA OIDC Manual Configuration Guide

This guide explains how to manually configure OpenID Connect (OIDC) authentication for the Interne Taak Afhandeling (ITA) application using Keycloak.

## 📋 Prerequisites

- Access to Keycloak Admin Console
- ITA application deployed via Helm
- Keycloak realm configured (e.g., `podiumd`)

## 🎯 Overview

ITA requires OIDC configuration to authenticate users through Keycloak. This involves:
1. Creating a Keycloak client for ITA
2. Configuring the client settings
3. Setting up protocol mappers
4. Creating required roles
5. Updating ITA configuration

## 🔧 Step 1: Create Keycloak Client

### Access Keycloak Admin Console
1. Navigate to your Keycloak admin console (e.g., `https://keycloak.example.nl/admin`)
2. Log in with admin credentials
3. Select your target realm (e.g., `podiumd`)

### Create New Client
1. Go to **Clients** in the left sidebar
2. Click **Create** button
3. Fill in the basic client information:
   - **Client ID**: `ita`
   - **Client Protocol**: `openid-connect`
   - **Root URL**: Leave empty
   - Click **Save**

## ⚙️ Step 2: Configure Client Settings

### General Settings
- **Client type**: OpenID Connect ✅
- **Client ID**: `ita` ✅
- **Name**: `ita` ✅
- **Description**: `Interne Taak Afhandeling - Internal Task Processing System`
- **Always display in UI**: On ✅

### Capability Config
- **Client Authentication**: Set to **"On"** (enables client credentials)
- **Authorization**: Leave **"Off"** (ITA doesn't need advanced authorization)
- **Authentication Flow**:
  - ✅ **Standard flow** (keep checked)
  - ❌ **Direct access grants** (uncheck)
  - ❌ **Implicit flow** (uncheck)
  - ❌ **Service accounts roles** (uncheck)
  - ❌ **Standard Token Exchange** (uncheck)
  - ❌ **OAuth 2.0 Device Authorization Grant** (uncheck)
  - ❌ **OIDC CIBA Grant** (uncheck)
- **PKCE Method**: Select **"S256"** (recommended for security)

### Login Settings
- **Root URL**: Leave empty
- **Home URL**: Leave empty
- **Valid redirect URIs**: Add your ITA application URL(s)
  - **For port forwarding access**: `http://localhost:3000/signin-oidc`
  - **For HTTPS port forwarding**: `https://localhost:3000/signin-oidc`
  - **For production with ingress**: `https://ita.example.nl/signin-oidc`
  - **Note**: The `/signin-oidc` path is required - this is ITA's callback endpoint
- **Valid post logout redirect URIs**: Add your ITA application URL(s)
  - **For port forwarding**: `http://localhost:3000/`
  - **For production**: `https://ita.example.nl/`
- **Web origins**: Add your ITA application URL(s)
  - **For port forwarding**: `http://localhost:3000`
  - **For production**: `https://ita.example.nl`

## 🔑 Step 3: Get Client Secret

1. Go to the **Credentials** tab
2. Copy the **Client Secret** - you'll need this for your ITA configuration
3. Keep this secret secure!

## 🗺️ Step 4: Configure Protocol Mappers

Go to the **Mappers** tab and add these protocol mappers:

### Username Mapper
- **Name**: `username`
- **Mapper Type**: `User Property`
- **Property**: `username`
- **Token Claim Name**: `preferred_username`
- **Claim JSON Type**: `String`
- **Full group path**: `false`
- **Add to ID token**: `true`
- **Add to access token**: `true`
- **Add to userinfo**: `true`

### Client Roles Mapper
- **Name**: `client roles`
- **Mapper Type**: `User Client Role`
- **Client ID**: `ita`
- **Token Claim Name**: `roles`
- **Claim JSON Type**: `String`
- **Full group path**: `false`
- **Add to ID token**: `true`
- **Add to access token**: `true`
- **Add to userinfo**: `false`

## 👥 Step 5: Create Required Roles

### Create Client Role
1. Go to **Roles**
2. Select the `ita` client
3. Click **Add Role**
4. **Role Name**: `ita-system-access`
5. **Description**: `Access to ITA system features`
6. Click **Save**

### Assign Roles to Users
1. Go to **Users**
2. Select a user who should have access to ITA
3. Go to **Role Mappings** tab
4. Select `ita` from the **Client Roles** dropdown
5. Add the `ita-system-access` role to the user

## 🚀 Step 6: Deploy ITA with OIDC Configuration

### For Port Forwarding Access

If you're accessing ITA via port forwarding (no ingress), follow these steps:

#### Option A: Automated Deployment (Recommended)

Use the provided deployment script that handles database initialization automatically:

1. **Set your Keycloak client secret** (optional, will use test secret if not set):
   ```bash
   export ITA_CLIENT_SECRET="your-actual-keycloak-client-secret"
   ```

2. **Run the deployment script**:
   ```bash
   ./scripts/deploy-ita.sh
   ```

3. **Set up port forwarding**:
   ```bash
   kubectl port-forward -n beproeving svc/ita-web-svc 3000:80
   ```

4. **Access ITA** at `http://localhost:3000`

#### Option B: Manual Deployment

1. **Deploy ITA**:
   ```bash
   helm upgrade --install ita -n beproving --create-namespace \
     oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling \
     --version 0.2.2 \
     --values charts/beproeving/values.yaml \
     --set web.oidc.clientSecret="your-actual-keycloak-client-secret"
   ```

2. **Set up port forwarding**:
   ```bash
   kubectl port-forward -n beproeving svc/ita-web-svc 3000:80
   ```

3. **Access ITA** at `http://localhost:3000`

4. **Important**: Make sure your Keycloak client has the correct redirect URI:
   - **Valid redirect URIs**: `http://localhost:3000/signin-oidc`
   - **Web origins**: `http://localhost:3000`

### For Production with Ingress

If you have ingress access, enable it in your values file and use the production URLs.

### Method 1: Using `--set` (Recommended for Development)

```bash
helm upgrade --install -n beproving --create-namespace \
  oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling \
  --version 0.2.2 \
  --values charts/beproeving/values.yaml \
  --set web.oidc.clientSecret="your-actual-keycloak-client-secret"
```

### Method 2: Using Environment Variable (Most Secure)

```bash
export ITA_CLIENT_SECRET="your-actual-keycloak-client-secret"

helm upgrade --install -n beproving --create-namespace \
  oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling \
  --version 0.2.2 \
  --values charts/beproeving/values.yaml \
  --set web.oidc.clientSecret="$ITA_CLIENT_SECRET"
```

### Method 3: Using Multiple `--set` Values

```bash
helm upgrade --install -n beproving --create-namespace \
  oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling \
  --version 0.2.2 \
  --values charts/beproeving/values.yaml \
  --set web.oidc.authority="https://your-keycloak-url/realms/your-realm" \
  --set web.oidc.clientId="ita" \
  --set web.oidc.clientSecret="your-actual-keycloak-client-secret" \
  --set web.oidc.itaSystemAccessRole="ita-system-access"
```

### Method 4: Using Separate Values File for Secrets

Create a `secrets.yaml` file (add to `.gitignore`):
```yaml
web:
  oidc:
    clientSecret: "your-actual-keycloak-client-secret"
```

Then use it:
```bash
helm upgrade --install -n beproving --create-namespace \
  oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling \
  --version 0.2.2 \
  --values charts/beproeving/values.yaml \
  --values secrets.yaml
```

## 📝 Current Configuration Reference

Based on the current `charts/beproeving/values.yaml`, the OIDC configuration should look like:

```yaml
web:
  oidc:
    authority: "https://your-keycloak-url/realms/your-realm"
    clientId: "ita"
    clientSecret: "your-actual-keycloak-client-secret"  # Set via command line
    itaSystemAccessRole: "ita-system-access"
    nameClaimType: "preferred_username"
    roleClaimType: "roles"
    objectregisterMedewerkerIdClaimType: "preferred_username"
    emailClaimType: "email"
```

## 🔍 Troubleshooting

### Common Issues

1. **"Missing required configuration value for 'OIDC_AUTHORITY'"**
   - Ensure `authority` is set correctly in your values
   - Check that the URL format is correct: `https://keycloak-url/realms/realm-name`

2. **Authentication fails**
   - Verify client secret matches between Keycloak and ITA configuration
   - Check that redirect URIs in Keycloak match your ITA application URL
   - Ensure users have the required `ita-system-access` role

3. **Redirect URI mismatch**
   - Make sure the redirect URI in Keycloak exactly matches your ITA application URL
   - **For port forwarding**: Use `http://localhost:3000/signin-oidc` (note the `/signin-oidc` path)
   - **For production**: Use `https://your-domain.com/signin-oidc`
   - The `/signin-oidc` path is required - this is ITA's callback endpoint

### Debug Steps

1. **Check ITA logs**:
   ```bash
   kubectl logs -n beproving deployment/ita-web
   ```

2. **Verify Keycloak client configuration**:
   - Check client is enabled
   - Verify protocol mappers are configured correctly
   - Ensure client secret is correct
   - **Verify redirect URI**: Must be exactly `http://localhost:3000/signin-oidc` for port forwarding

3. **Test OIDC flow**:
   - Set up port forwarding: `kubectl port-forward -n beproving svc/ita-web-svc 3000:80`
   - Access ITA at `http://localhost:3000`
   - Check if redirect to Keycloak works
   - Verify successful authentication and redirect back

4. **Check the actual redirect URI being sent**:
   ```bash
   curl -I http://localhost:3000
   ```
   Look for the `Location` header in the response to see the exact redirect URI being sent to Keycloak.

## 🔒 Security Best Practices

1. **Never commit secrets** to version control
2. **Use environment variables** to avoid secrets in shell history
3. **Consider using Kubernetes secrets** for production deployments
4. **Rotate client secrets regularly**
5. **Use HTTPS** for all production URLs
6. **Limit redirect URIs** to only necessary domains
7. **Enable PKCE** for additional security
8. **For port forwarding**: Only use localhost redirect URIs during development
9. **For production**: Use proper domain names and HTTPS redirect URIs

## 📚 Additional Resources

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OpenID Connect Specification](https://openid.net/connect/)
- [OAuth 2.0 Security Best Practices](https://tools.ietf.org/html/draft-ietf-oauth-security-topics)

---

**Note**: This configuration enables ITA to authenticate users through Keycloak using the standard OAuth2 authorization code flow with PKCE for enhanced security. 

## 🎯 **Key Points for Port Forwarding:**

- **Redirect URI**: Must be exactly `http://localhost:3000/signin-oidc` (note the `/signin-oidc` path)
- **Web Origin**: Must be `http://localhost:3000`
- **Service Name**: ITA creates a service named `ita-web-svc` for port forwarding
- **Port Forwarding Command**: `kubectl port-forward -n beproeving svc/ita-web-svc 3000:80`

## 🗄️ **Database Initialization:**

The deployment script automatically handles database initialization:

- **Checks if the "ita" user exists** in PostgreSQL
- **Creates the user if it doesn't exist** with proper privileges
- **Grants necessary permissions** for the ITA application
- **Runs before the main application starts** to ensure database readiness

This ensures that ITA will have the proper database access when it starts up.

🚀

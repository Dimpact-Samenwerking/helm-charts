# API Proxy URL Rewriting

## Overview

The API proxy (nginx-based) supports URL rewriting in response bodies from external API providers (iConnect, 2Secure). This is useful when external APIs return URLs pointing to their endpoints, but you need to rewrite them to point to the internal proxy instead.

## Use Case

When the BAG API (or other external APIs) returns responses containing URLs like:
```json
{
  "_links": {
    "self": {
      "href": "https://lab.api.mijniconnect.nl/iconnect/apibagib/v2/adressen/123456"
    }
  }
}
```

You want clients to use the internal proxy URL instead:
```json
{
  "_links": {
    "self": {
      "href": "https://api-proxy.example.nl/lvbag/individuelebevragingen/v2/adressen/123456"
    }
  }
}
```

## Configuration

### Enable URL Rewriting for BAG

In your `values.yaml` or environment-specific values file:

```yaml
apiproxy:
  enabled: true
  locations:
    bag:
      path: /lvbag/individuelebevragingen/v2/
      targetUrl: "https://lab.api.mijniconnect.nl/iconnect/apibagib/v2/"
      hostHeader: "lab.api.mijniconnect.nl"
      sslVerify: "off"
      urlRewrite:
        enabled: true  # Enable response URL rewriting
        internalUrl: "https://your-public-domain.nl/lvbag/individuelebevragingen/v2/"
```

### Important Configuration Notes

1. **`internalUrl`** - Must be the **public-facing URL** where clients access the api-proxy
   - For internal cluster access: `http://api-proxy.podiumd.svc.cluster.local/lvbag/individuelebevragingen/v2/`
   - For external access: `https://api.your-municipality.nl/lvbag/individuelebevragingen/v2/`

2. **Content Types** - URL rewriting works for:
   - `application/json`
   - `application/hal+json`
   - `text/html`

3. **Performance Impact** - Nginx must:
   - Disable compression (`Accept-Encoding: ""`)
   - Buffer entire response body
   - Perform string replacement

## How It Works

The nginx `sub_filter` module:
1. Intercepts responses from the external API
2. Searches for the `targetUrl` in the response body
3. Replaces all occurrences with `internalUrl`
4. Returns the modified response to the client

## Example Deployment

### For Assen Environment

```yaml
# values-asse.yaml
apiproxy:
  enabled: true
  locations:
    bag:
      urlRewrite:
        enabled: true
        internalUrl: "https://api.assen.nl/lvbag/individuelebevragingen/v2/"
```

### For Groningen Environment

```yaml
# values-gron.yaml
apiproxy:
  enabled: true
  locations:
    bag:
      urlRewrite:
        enabled: true
        internalUrl: "https://api.groningen.nl/lvbag/individuelebevragingen/v2/"
```

## Testing

### 1. Deploy with URL Rewriting Enabled

```bash
helm upgrade --install podiumd dimpact/podiumd \
  -f values-custom.yaml \
  --set apiproxy.enabled=true \
  --set apiproxy.locations.bag.urlRewrite.enabled=true
```

### 2. Test a BAG Request

```bash
# Make request through the proxy
curl -H "X-Api-Key: your-key" \
  https://your-domain.nl/lvbag/individuelebevragingen/v2/adressen/0200010000130331

# Check if URLs in response point to your-domain.nl instead of lab.api.mijniconnect.nl
```

### 3. Verify URL Rewriting

Look for `_links` or `href` fields in the response - they should contain your `internalUrl`, not the external `targetUrl`.

## Limitations

1. **Performance**: String replacement on every response adds latency
2. **Compression**: Must disable compression for `sub_filter` to work
3. **Exact Match**: Only replaces exact string matches of `targetUrl`
4. **Text-based**: Only works on text-based response types (JSON, XML, HTML)
5. **Memory**: Entire response must be buffered in nginx

## Advanced: Multiple URL Replacements

If BAG responses contain multiple different external URLs, you can add multiple `sub_filter` directives:

```nginx
sub_filter 'https://lab.api.mijniconnect.nl/iconnect/apibagib/v2/' 'https://api.example.nl/lvbag/individuelebevragingen/v2/';
sub_filter 'https://api.bag.kadaster.nl/' 'https://api.example.nl/lvbag/';
sub_filter_once off;
```

However, the current Helm template only supports one replacement per location. For multiple replacements, you would need to extend the template.

## Troubleshooting

### URLs Not Being Rewritten

1. Check `urlRewrite.enabled` is `true`
2. Verify `internalUrl` is correctly set
3. Check nginx logs: `kubectl logs -n podiumd deployment/api-proxy`
4. Verify response Content-Type is supported

### Compressed Responses

If responses are still compressed:
- Check if `proxy_set_header Accept-Encoding "";` is present in nginx config
- Some backends ignore this header - might need to add `proxy_buffering on;`

### Performance Issues

- Consider if URL rewriting is necessary for your use case
- Evaluate using a more powerful proxy (Kong, Tyk) for complex transformations
- Monitor nginx memory usage with rewriting enabled

## Related Documentation

- [NGINX sub_filter Module](http://nginx.org/en/docs/http/ngx_http_sub_module.html)
- BAG API Specification: [Kadaster BAG API](https://lvbag.github.io/BAG-API/)
- Helm Chart README: `charts/podiumd/README.md`

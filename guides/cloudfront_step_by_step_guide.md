# AWS CloudFront — Step-by-Step Configuration Guide

This is a click-by-click walkthrough for every setting listed in the [CloudFront Settings Guide](file:///c:/Users/admin/.gemini/antigravity-ide/brain/170af2b3-20c2-49f4-acaf-f4410d5e0b3e/cloudfront_settings_guide.md). Follow each section in order.

> [!IMPORTANT]
> You have **two** CloudFront distributions to configure:
> - **API Distribution**: `d1ade3v18apdww.cloudfront.net` → ALB port 8000
> - **UI Distribution**: `d1skrvdhe4yz1l.cloudfront.net` → ALB port 3010
>
> Each section specifies which distribution it applies to.

---

# Part 1 — File Upload Settings

> Applies to: **API Distribution** (`d1ade3v18apdww`)

---

## Step 1.1 — Enable All HTTP Methods

By default, CloudFront only allows GET and HEAD. File uploads require POST, PUT, DELETE, and OPTIONS.

1. Open the **AWS Console** → go to **CloudFront**
2. Click on distribution **`d1ade3v18apdww`**
3. Click the **Behaviors** tab
4. Select the **Default (*)** behavior → click **Edit**
5. Scroll to **Allowed HTTP methods**
6. Select: **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**
7. Under that, a checkbox will appear: **Cache HTTP methods** → ensure **OPTIONS** is checked
8. **Don't save yet** — continue to Step 1.2 (you're still editing this behavior)

> [!NOTE]
> This is the single most important change for file uploads. Without this, every `POST` to `/api/v1/knowledge-base/upload` or `/api/v1/s3-signed-url/upload-csv` will return a `403 Forbidden` from CloudFront before it ever reaches your backend.

---

## Step 1.2 — Disable Caching (Cache Policy)

API responses must never be cached. A cached presigned URL will expire and break uploads.

1. Still editing the **Default (*)** behavior from Step 1.1
2. Scroll to the **Cache key and origin requests** section
3. Select **Cache policy and origin request policy (recommended)**
4. For **Cache policy**, click the dropdown and select:
   ```
   CachingDisabled
   ```
   > This is an AWS-managed policy. If you don't see it, search for "CachingDisabled" in the dropdown.
5. **Don't save yet** — continue to Step 1.3

> [!TIP]
> If you prefer a custom cache policy instead of the managed one:
> 1. Go to **CloudFront** → **Policies** → **Cache** tab → **Create cache policy**
> 2. Name: `Dograh-API-NoCaching`
> 3. Set all TTL values to **0**:
>    - Minimum TTL: `0`
>    - Maximum TTL: `0`
>    - Default TTL: `0`
> 4. **Cache key contents**: Leave headers, cookies, and query strings to **None** (since we're not caching)
> 5. Click **Create**
> 6. Go back to the behavior and select this custom policy

---

## Step 1.3 — Forward All Headers (Origin Request Policy)

The backend needs `Authorization`, `Content-Type`, `Origin`, cookies, and query strings to function.

1. Still editing the **Default (*)** behavior
2. In the same **Cache key and origin requests** section
3. For **Origin request policy**, click the dropdown and select:
   ```
   AllViewer
   ```
   > This is an AWS-managed policy that forwards ALL viewer headers, cookies, and query strings to the origin.

4. If `AllViewer` is not available or you get errors about header conflicts with the cache policy, select:
   ```
   AllViewerExceptHostHeader
   ```
   > This is usually the safer choice — it forwards everything except the `Host` header, which CloudFront replaces with the origin's hostname.

5. Now click **Save changes**

> [!WARNING]
> Do NOT use `AllViewer` if your origin (ALB) requires the `Host` header to match the ALB's DNS name. In that case, use `AllViewerExceptHostHeader`. If the ALB doesn't have host-based routing rules, either will work.

---

## Step 1.4 — Increase Origin Timeouts

Large file uploads (up to 100 MB for knowledge base documents) can take longer than the default 30-second timeout.

1. Still in distribution **`d1ade3v18apdww`**
2. Click the **Origins** tab
3. Select your origin (the ALB: `dograh-alb-2113815158.ap-south-1.elb.amazonaws.com`) → click **Edit**
4. Scroll down to **Additional settings** (expand if collapsed)
5. Set the following:
   - **Response timeout (Origin read timeout)**: `60` seconds
     > Default is 30. This is how long CloudFront waits for the origin to start sending a response.
   - **Keep-alive timeout**: `60` seconds
     > Default is 5. This keeps the TCP connection between CloudFront and ALB alive longer, reducing reconnection overhead for sequential requests.
6. Click **Save changes**

> [!NOTE]
> If users are uploading 100 MB files on slow mobile networks (e.g., 2 Mbps), even 60s might not be enough. A 100 MB file at 2 Mbps takes ~400 seconds. However, the Origin Read Timeout measures time-to-first-byte from the origin — not total transfer time. Once the backend starts reading the multipart stream, the timeout resets. So 60s is sufficient in practice.

---

## Step 1.5 — MinIO Presigned URL Routing

Your `MINIO_PUBLIC_ENDPOINT` is currently `dograh-alb-2113815158.ap-south-1.elb.amazonaws.com:9001`. Browser uploads via presigned URLs go directly to the ALB, bypassing CloudFront.

### Option A: Keep Direct ALB Access (Simplest — Recommended)

1. Open **AWS Console** → **EC2** → **Security Groups**
2. Find the security group attached to your ALB (`dograh-alb-2113815158`)
3. Click **Edit inbound rules**
4. Add a rule:
   - **Type**: Custom TCP
   - **Port range**: `9001`
   - **Source**: `0.0.0.0/0` (or restrict to known IPs for security)
   - **Description**: `MinIO presigned URL access`
5. Click **Save rules**

> [!NOTE]
> No CloudFront or ECS changes needed. This just ensures port 9001 is accessible from the internet.

### Option B: Route MinIO Through CloudFront

If you want presigned URLs to go through CloudFront for SSL termination and caching:

1. Open **CloudFront** → distribution **`d1ade3v18apdww`** → **Origins** tab
2. Click **Create origin**
3. Configure:
   - **Origin domain**: `dograh-alb-2113815158.ap-south-1.elb.amazonaws.com`
   - **Protocol**: HTTP only
   - **HTTP port**: `9001`
   - **Origin name**: `dograh-minio`
4. Click **Create origin**
5. Go to **Behaviors** tab → click **Create behavior**
6. Configure:
   - **Path pattern**: `/voice-audio/*`
     > This matches your MinIO bucket name from the task definition
   - **Origin and origin group**: Select `dograh-minio` (the one you just created)
   - **Allowed HTTP methods**: `GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE`
   - **Cache policy**: `CachingDisabled`
   - **Origin request policy**: `AllViewerExceptHostHeader`
   - **Viewer protocol policy**: `Redirect HTTP to HTTPS`
7. Click **Create behavior**
8. Update the ECS task definition environment variable:
   ```json
   {
     "name": "MINIO_PUBLIC_ENDPOINT",
     "value": "d1ade3v18apdww.cloudfront.net"
   }
   ```
9. Redeploy the API ECS service

### Option C: Switch to AWS S3 (Cleanest for Production)

1. Create an S3 bucket (e.g., `dograh-audio-recordings`) in `ap-south-1`
2. Configure CORS on the bucket:
   - Go to **S3** → your bucket → **Permissions** → **Cross-origin resource sharing (CORS)**
   - Click **Edit** and paste:
   ```json
   [
     {
       "AllowedHeaders": ["*"],
       "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
       "AllowedOrigins": ["https://d1skrvdhe4yz1l.cloudfront.net"],
       "ExposeHeaders": ["ETag"]
     }
   ]
   ```
3. Ensure the ECS Task Role has S3 permissions:
   - Go to **IAM** → **Roles** → `ecsTaskExecutionRole`
   - Attach an inline policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:PutObject",
           "s3:DeleteObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::dograh-audio-recordings",
           "arn:aws:s3:::dograh-audio-recordings/*"
         ]
       }
     ]
   }
   ```
4. Update ECS task definition environment variables:
   ```json
   { "name": "ENABLE_AWS_S3", "value": "true" },
   { "name": "S3_BUCKET", "value": "dograh-audio-recordings" },
   { "name": "S3_REGION", "value": "ap-south-1" }
   ```
5. Redeploy the API ECS service

---

# Part 2 — Voice Conversation Settings

> Applies to: **API Distribution** (`d1ade3v18apdww`) + **ALB**

---

## Step 2.1 — Configure Origin Protocol Policy for WebSocket Support

CloudFront only supports WebSocket when the connection is over HTTPS/WSS.

1. Open **CloudFront** → distribution **`d1ade3v18apdww`**
2. Click the **Origins** tab
3. Select your ALB origin → click **Edit**
4. Find **Protocol** (also called "Origin Protocol Policy")
5. Choose one of the following:

   **If your ALB has an HTTPS listener (port 443 with ACM certificate):**
   ```
   ✅ Select: "HTTPS only"
   ```

   **If your ALB only has an HTTP listener (port 8000):**
   ```
   ✅ Select: "HTTP only"
   ```
   > ⚠️ This means WebSockets through CloudFront will NOT work. CloudFront requires HTTPS to the origin for WebSocket. You'll need to keep the current hybrid approach (direct ALB for WS).

   **If you want flexibility:**
   ```
   ✅ Select: "Match Viewer"
   ```
   > CloudFront will use the same protocol as the viewer. If the viewer connects via HTTPS, CloudFront connects via HTTPS to origin.

6. Click **Save changes**

> [!IMPORTANT]
> **To make WebSockets work through CloudFront, your ALB MUST have an HTTPS listener.** Here's how to add one if you don't have it:
> 1. Go to **EC2** → **Load Balancers** → select your ALB
> 2. Click **Listeners** tab → **Add listener**
> 3. **Protocol**: HTTPS, **Port**: 443
> 4. **Default action**: Forward to your API target group (port 8000)
> 5. **Security policy**: `ELBSecurityPolicy-TLS13-1-2-2021-06`
> 6. **Default SSL/TLS certificate**: Select an ACM certificate for your domain
> 7. Click **Add**
> 8. Update the CloudFront origin to use port 443 and HTTPS only

---

## Step 2.2 — WebSocket Idle Timeout (Understanding the Limitation)

> [!WARNING]
> CloudFront has a **hard-coded 10-minute idle timeout** for WebSocket connections. This CANNOT be changed. There is no setting to modify.

### If you choose the Hybrid Approach (Recommended):

Keep WebSocket traffic going directly to the ALB. No changes needed here.

Your current setup is:
```
HTTP API   → CloudFront → ALB:8000  (BACKEND_API_ENDPOINT)
WebSocket  → Direct ALB:8000        (BACKEND_WS_ENDPOINT)
```

**Ensure the ALB is accessible for direct WebSocket connections:**

1. Go to **EC2** → **Security Groups** → find the ALB security group
2. **Edit inbound rules**
3. Verify this rule exists:
   - **Type**: Custom TCP
   - **Port range**: `8000`
   - **Source**: `0.0.0.0/0` (or your Vobiz/Twilio webhook IPs)
   - **Description**: `API + WebSocket direct access`
4. **Save rules**

### If you choose CloudFront for Everything:

You must implement WebSocket keepalive pings in your voice pipeline code:

1. In your codebase, find the WebSocket transport in the Pipecat engine
2. Add a ping/pong frame every **30 seconds** to prevent CloudFront from timing out
3. Update the ECS task definition:
   ```json
   {
     "name": "BACKEND_WS_ENDPOINT",
     "value": "wss://d1ade3v18apdww.cloudfront.net"
   }
   ```
4. Redeploy the API ECS service

> [!CAUTION]
> Even with keepalives, if a caller puts the call on mute for more than 10 minutes with zero audio frames, CloudFront will kill the connection. The hybrid approach avoids this risk entirely.

---

## Step 2.3 — ALB Idle Timeout (Critical — Not CloudFront)

This is the most important setting for voice calls. It's on the ALB, not CloudFront.

1. Open **AWS Console** → **EC2** → **Load Balancers**
2. Select your ALB: `dograh-alb-2113815158`
3. Click the **Attributes** tab (or scroll down to **Attributes**)
4. Click **Edit**
5. Find **Idle timeout**
6. Change the value to:
   ```
   3600
   ```
   > This is 1 hour (3600 seconds). The default is 60 seconds, which would kill any voice call longer than 1 minute of silence.
7. Click **Save changes**

> [!NOTE]
> This setting determines how long the ALB waits for data on an idle connection before closing it. For voice calls, there can be pauses (hold music, user thinking, etc.) so 1 hour is safe.

---

## Step 2.4 — TURN/STUN Configuration (WebRTC — No CloudFront Changes)

Browser "Web Call" uses WebRTC with a coTURN server. This is purely UDP/TCP between the browser and the TURN server — it does NOT go through CloudFront.

**No CloudFront changes needed.** But verify your coTURN setup:

1. Ensure the `TURN_HOST` in your ECS task definition points to an accessible TURN server
   - Currently: `localhost` (which means the TURN server runs in the same ECS task)
2. Ensure these ports are open on the ECS task's security group:
   - **3478/TCP+UDP** — STUN/TURN signaling
   - **49152-65535/UDP** — TURN relay media range
3. Ensure the `TURN_SECRET` matches between the API and the coTURN server

> [!NOTE]
> Your current `TURN_HOST: localhost` means the coTURN server is expected to run inside the same ECS task. If it's not deployed there, Web Calls from the browser won't work (phone calls via Vobiz/Twilio are unaffected — they don't use WebRTC).

---

# Part 3 — Security Settings

> Applies to: **Both Distributions**

---

## Step 3.1 — CORS Configuration (API Distribution)

Your UI makes cross-origin requests to the API. CORS headers must be handled.

### Recommended Approach: Let FastAPI Handle CORS

Your backend already has CORS middleware. Just ensure CloudFront forwards the `Origin` header.

1. Open **CloudFront** → distribution **`d1ade3v18apdww`**
2. Click **Behaviors** → select **Default (*)** → **Edit**
3. Verify the **Origin request policy** is set to `AllViewer` or `AllViewerExceptHostHeader`
   > This forwards the `Origin` header to FastAPI, which then responds with the correct `Access-Control-Allow-Origin` header
4. Click **Save changes**

**That's it!** FastAPI handles the CORS response headers.

### Alternative: CloudFront Response Headers Policy for CORS

If you prefer CloudFront to inject CORS headers (instead of relying on the backend):

1. Go to **CloudFront** → **Policies** (left sidebar) → **Response headers** tab
2. Click **Create response headers policy**
3. **Name**: `Dograh-API-CORS`
4. Expand **Cross-origin resource sharing (CORS)** section
5. Toggle **Configure CORS** → **On**
6. Fill in:
   - **Access-Control-Allow-Origin**:
     - Select **Customize**
     - Add: `https://d1skrvdhe4yz1l.cloudfront.net`
     - If you have other domains, add them too
   - **Access-Control-Allow-Headers**:
     - Add: `Authorization`, `Content-Type`, `X-Requested-With`, `Accept`, `Origin`
   - **Access-Control-Allow-Methods**:
     - Check: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS`
   - **Access-Control-Allow-Credentials**: `true`
   - **Access-Control-Max-Age**: `86400`
   - **Origin override**: `Yes`
     > This ensures CloudFront's CORS headers replace any backend CORS headers, avoiding duplicates
7. Click **Create**
8. Go back to distribution **`d1ade3v18apdww`** → **Behaviors** → **Default (*)** → **Edit**
9. For **Response headers policy**, select `Dograh-API-CORS`
10. Click **Save changes**

---

## Step 3.2 — HTTPS / TLS (Both Distributions)

### API Distribution (`d1ade3v18apdww`)

1. Open **CloudFront** → distribution **`d1ade3v18apdww`**
2. Click **Behaviors** → select **Default (*)** → **Edit**
3. Find **Viewer protocol policy**
4. Select:
   ```
   Redirect HTTP to HTTPS
   ```
5. Click **Save changes**
6. Go to **General** tab → **Settings** → click **Edit**
7. Scroll to **Custom SSL certificate**:
   - If using `*.cloudfront.net` domain: Leave as default (CloudFront's built-in certificate)
   - If using a custom domain: Click **Request or import a certificate with ACM**
8. Scroll to **Supported HTTP versions**:
   - Check **HTTP/2** (recommended for performance)
   - Optionally check **HTTP/3** for even better performance
9. Under **Security policy** (minimum SSL/TLS protocol):
   - Select: `TLSv1.2_2021` (recommended)
10. Click **Save changes**

### UI Distribution (`d1skrvdhe4yz1l`)

1. Repeat the exact same steps (2–10) for distribution **`d1skrvdhe4yz1l`**
2. Ensure **Viewer protocol policy** is set to `Redirect HTTP to HTTPS`

---

## Step 3.3 — Geo-Restriction

Restrict access to countries where your service operates.

### API Distribution (`d1ade3v18apdww`)

1. Open **CloudFront** → distribution **`d1ade3v18apdww`**
2. Go to **General** tab → **Settings** → click **Edit**
3. Scroll down to **CloudFront geographic restrictions**
4. Select **Restriction type**:
   ```
   Allow list
   ```
5. Add countries:
   - **IN** — India (your primary market, ALB is in ap-south-1)
   - Add any other countries where your users or Vobiz/Twilio webhooks originate
6. Click **Save changes**

> [!WARNING]
> **Do NOT enable geo-restriction if Vobiz webhook servers are outside India.** Check your Vobiz documentation for their webhook origin IPs. The IP `35.154.59.246` (seen in your logs) is in `ap-south-1` (India), so India should be safe.

### UI Distribution (`d1skrvdhe4yz1l`)

1. Repeat the same steps for the UI distribution
2. Add the same countries as the API distribution

---

## Step 3.4 — WAF (Web Application Firewall)

Attach AWS WAF to protect your API from abuse.

### Step 3.4.1 — Create a WAF Web ACL

1. Open **AWS Console** → search for **WAF & Shield** → click **AWS WAF**
2. Make sure the region is set to **Global (CloudFront)** in the top-right
   > WAF for CloudFront MUST be created in `us-east-1` / Global
3. Click **Web ACLs** → **Create web ACL**
4. **Step 1 — Describe**:
   - **Name**: `Dograh-API-WAF`
   - **Description**: `WAF rules for Dograh API CloudFront distribution`
   - **Resource type**: `CloudFront distributions`
   - **Associated AWS resources**: Click **Add AWS resources** → select distribution `d1ade3v18apdww` → **Add**
   - Click **Next**

5. **Step 2 — Add rules**:

   #### Rule 1: Rate Limiting for Telephony Endpoints
   - Click **Add rules** → **Add my own rules and rule groups**
   - **Rule type**: `Rate-based rule`
   - **Name**: `RateLimit-Telephony`
   - **Rate limit**: `100` requests per 5 minutes
   - **Scope of inspection**: Select **Only consider requests that match the criteria in a rule statement**
   - **Statement**:
     - **Inspect**: `URI path`
     - **Match type**: `Starts with string`
     - **String to match**: `/api/v1/telephony/`
   - **Action**: `Block`
   - Click **Add rule**

   #### Rule 2: Rate Limiting for Auth Endpoints
   - Click **Add rules** → **Add my own rules and rule groups**
   - **Rule type**: `Rate-based rule`
   - **Name**: `RateLimit-Auth`
   - **Rate limit**: `20` requests per 5 minutes
   - **Scope**: Only requests matching:
     - **Inspect**: `URI path`
     - **Match type**: `Starts with string`
     - **String to match**: `/api/v1/auth/`
   - **Action**: `Block`
   - Click **Add rule**

   #### Rule 3: AWS Managed Core Rule Set
   - Click **Add rules** → **Add managed rule groups**
   - Expand **AWS managed rule groups**
   - Toggle ON: **Core rule set (CRS)**
     > This protects against common web exploits (XSS, SQL injection, etc.)
   - Toggle ON: **Known bad inputs**
   - Click **Add rules**

   #### Rule 4: IP Allowlist for Vobiz Webhooks (Optional)
   - First, create an IP set:
     - Go to **WAF** → **IP sets** → **Create IP set**
     - **Name**: `Vobiz-Webhook-IPs`
     - **Region**: `Global (CloudFront)`
     - **IP version**: IPv4
     - **IP addresses**: Add Vobiz IPs (one per line):
       ```
       35.154.59.246/32
       ```
       > Add all Vobiz webhook origin IPs here
     - Click **Create IP set**
   - Back in the Web ACL rule creation:
     - Click **Add rules** → **Add my own rules**
     - **Rule type**: `Regular rule`
     - **Name**: `Allow-Vobiz-IPs`
     - **Statement**:
       - **Inspect**: `Originates from an IP address in`
       - **IP set**: Select `Vobiz-Webhook-IPs`
       - Add **AND** condition:
         - **Inspect**: `URI path`
         - **Match type**: `Starts with string`
         - **String to match**: `/api/v1/telephony/`
     - **Action**: `Allow`
     - Click **Add rule**
     - **IMPORTANT**: Move this rule ABOVE the rate limiting rule using the priority arrows

6. **Step 3 — Set rule priority**:
   - Drag to reorder (top = highest priority):
     1. `Allow-Vobiz-IPs` (allow known webhook sources first)
     2. `RateLimit-Telephony`
     3. `RateLimit-Auth`
     4. `AWS-AWSManagedRulesCommonRuleSet`
     5. `AWS-AWSManagedRulesKnownBadInputsRuleSet`
   - Click **Next**

7. **Step 4 — Configure metrics**: Leave defaults → **Next**

8. **Step 5 — Review**: Review all rules → click **Create web ACL**

---

## Step 3.5 — Security Headers (UI Distribution)

Add security response headers to the UI distribution to protect against clickjacking, XSS, and other attacks.

### Step 3.5.1 — Create a Response Headers Policy

1. Go to **CloudFront** → **Policies** (left sidebar) → **Response headers** tab
2. Click **Create response headers policy**
3. **Name**: `Dograh-UI-Security-Headers`

4. Expand **Security headers** section:

   #### Strict-Transport-Security (HSTS)
   - Toggle **ON**
   - **Max-age**: `31536000` (1 year)
   - Check: **Include subdomains**
   - Check: **Preload** (optional — adds your domain to browser HSTS preload lists)
   - **Origin override**: `No`

   #### X-Content-Type-Options
   - Toggle **ON**
   - Value is automatically set to `nosniff`
   - **Origin override**: `Yes`

   #### X-Frame-Options
   - Toggle **ON**
   - Select: `DENY`
     > Prevents your dashboard from being embedded in iframes (clickjacking protection)
   - **Origin override**: `Yes`

   #### X-XSS-Protection
   - Toggle **ON**
   - Select: `1; mode=block`
   - **Origin override**: `Yes`

   #### Referrer-Policy
   - Toggle **ON**
   - Select: `strict-origin-when-cross-origin`
   - **Origin override**: `Yes`

   #### Content-Security-Policy
   - Toggle **ON**
   - Value:
     ```
     default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' https://d1ade3v18apdww.cloudfront.net wss://d1ade3v18apdww.cloudfront.net ws://dograh-alb-2113815158.ap-south-1.elb.amazonaws.com:8000; font-src 'self' data:; media-src 'self' blob:;
     ```
   - **Origin override**: `No`

   > [!WARNING]
   > The CSP above is permissive (`unsafe-inline`, `unsafe-eval`) to avoid breaking Next.js. Test thoroughly after applying. If the dashboard breaks, start by removing `Content-Security-Policy` and adding it back with a `Content-Security-Policy-Report-Only` header first.

5. Click **Create**

### Step 3.5.2 — Attach the Policy to the UI Distribution

1. Open **CloudFront** → distribution **`d1skrvdhe4yz1l`**
2. Click **Behaviors** → select **Default (*)** → **Edit**
3. Scroll to **Response headers policy**
4. Select: `Dograh-UI-Security-Headers`
5. Click **Save changes**

---

## Step 3.6 — HTTPS/TLS for API-to-Backend Security Headers Policy

Apply a lighter security headers policy to the API distribution too.

1. Go to **CloudFront** → **Policies** → **Response headers** tab
2. Click **Create response headers policy**
3. **Name**: `Dograh-API-Security-Headers`
4. Under **Security headers**:
   - **Strict-Transport-Security**: ON, max-age `31536000`, include subdomains
   - **X-Content-Type-Options**: ON, `nosniff`
5. If you created a separate CORS policy in Step 3.1 (alternative approach), you can merge it here
6. Click **Create**
7. Go to distribution **`d1ade3v18apdww`** → **Behaviors** → **Default (*)** → **Edit**
8. For **Response headers policy**, select `Dograh-API-Security-Headers`
9. Click **Save changes**

---

## Step 3.7 — Migrate Secrets from Plaintext to AWS Secrets Manager

Your ECS task definitions contain plaintext credentials. Here's how to migrate them.

> [!CAUTION]
> This step modifies your ECS task definition. Test in a staging environment first.

### Step 3.7.1 — Create Secrets in AWS Secrets Manager

1. Open **AWS Console** → **Secrets Manager**
2. Click **Store a new secret**
3. **Secret type**: `Other type of secret`
4. Add key-value pairs for your first secret group:
   ```
   MINIO_ACCESS_KEY     = minioadmin
   MINIO_SECRET_KEY     = minioadmin
   POSTGRES_PASSWORD    = postgres
   REDIS_PASSWORD       = redissecret
   TURN_SECRET          = dograh-turn-secret-change-in-production
   ```
5. Click **Next**
6. **Secret name**: `dograh/production/credentials`
7. **Description**: `Dograh production database, Redis, MinIO, and TURN credentials`
8. Click **Next** → **Next** → **Store**

### Step 3.7.2 — Grant ECS Task Access to Secrets

1. Go to **IAM** → **Roles** → find `ecsTaskExecutionRole`
2. Click **Add permissions** → **Attach policies** → **Create inline policy**
3. Switch to **JSON** tab and paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "secretsmanager:GetSecretValue"
         ],
         "Resource": [
           "arn:aws:secretsmanager:ap-south-1:968246764501:secret:dograh/production/credentials-*"
         ]
       }
     ]
   }
   ```
4. **Policy name**: `DograhSecretsAccess`
5. Click **Create policy**

### Step 3.7.3 — Update ECS Task Definition to Use Secrets

1. Go to **ECS** → **Task Definitions** → `dograh-api`
2. Click **Create new revision**
3. For each container that uses credentials, change the `environment` entries to `secrets`:

**Before (current — plaintext):**
```json
"environment": [
  { "name": "MINIO_ACCESS_KEY", "value": "minioadmin" },
  { "name": "MINIO_SECRET_KEY", "value": "minioadmin" }
]
```

**After (using Secrets Manager):**
```json
"secrets": [
  {
    "name": "MINIO_ACCESS_KEY",
    "valueFrom": "arn:aws:secretsmanager:ap-south-1:968246764501:secret:dograh/production/credentials:MINIO_ACCESS_KEY::"
  },
  {
    "name": "MINIO_SECRET_KEY",
    "valueFrom": "arn:aws:secretsmanager:ap-south-1:968246764501:secret:dograh/production/credentials:MINIO_SECRET_KEY::"
  }
]
```

> The format is: `arn:aws:secretsmanager:REGION:ACCOUNT:secret:SECRET_NAME:JSON_KEY:VERSION_STAGE:VERSION_ID`
> Leave `VERSION_STAGE` and `VERSION_ID` empty (the trailing `::`) to use the latest version.

4. Similarly update:
   - `REDIS_URL` → extract the password from secrets and construct the URL
   - `DATABASE_URL` → extract the password from secrets
   - `TURN_SECRET` → reference from secrets
5. Repeat for ALL containers in the task definition (`dograh-api`, `ari-manager`, `campaign-orchestrator`, `arq-worker`)
6. Click **Create** to register the new revision
7. Go to **ECS** → **Services** → **dograh-api-service** → **Update** → select the new task revision → **Update**

---

# Part 4 — Verification Checklist

After making all changes, verify each feature works:

## File Upload Verification
- [ ] Upload a knowledge base document (< 5 MB) via the dashboard
- [ ] Upload a knowledge base document (> 10 MB) to test timeout settings
- [ ] Upload a CSV contact list
- [ ] Upload a workflow audio recording
- [ ] Verify presigned URLs work (document preview/download)

## Voice Call Verification
- [ ] Make an inbound call via Vobiz → verify call connects and voice is heard
- [ ] Make an outbound call from the dashboard → verify call connects
- [ ] Make a "Web Call" from the browser → verify WebRTC audio works
- [ ] Hold a call for 5+ minutes to verify ALB timeout is sufficient

## Security Verification
- [ ] Access `http://d1skrvdhe4yz1l.cloudfront.net` → verify it redirects to `https://`
- [ ] Access `http://d1ade3v18apdww.cloudfront.net` → verify it redirects to `https://`
- [ ] Open browser DevTools → Network tab → check response headers for HSTS, X-Frame-Options
- [ ] Make an API call from the UI → verify CORS headers are present
- [ ] Try accessing from a geo-restricted country (if configured) → verify it's blocked

## Quick Test Commands

```bash
# Test HTTPS redirect
curl -I http://d1ade3v18apdww.cloudfront.net/api/v1/health

# Test API reachability
curl -I https://d1ade3v18apdww.cloudfront.net/api/v1/health

# Test CORS preflight
curl -X OPTIONS \
  -H "Origin: https://d1skrvdhe4yz1l.cloudfront.net" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Authorization,Content-Type" \
  -I https://d1ade3v18apdww.cloudfront.net/api/v1/health

# Test security headers on UI
curl -I https://d1skrvdhe4yz1l.cloudfront.net

# Test file upload endpoint reachability (should return 405 or 422, NOT 403)
curl -X POST -I https://d1ade3v18apdww.cloudfront.net/api/v1/knowledge-base/upload
```

> [!NOTE]
> CloudFront changes take **5-15 minutes** to propagate globally. If a change doesn't seem to work immediately, wait and try again. You can check propagation status in the CloudFront console — it shows "Deploying" while changes propagate.

# Weibo Publisher Workflow Examples

## Example 1: Text-Only Post

```javascript
// 1. Open compose page
browser open https://m.weibo.cn/compose

// 2. Get snapshot to find refs
browser snapshot

// 3. Type content
browser act kind=type ref=e15 text="Hello Weibo!"

// 4. Click send
browser act kind=click ref=e10

// 5. Wait and verify
exec "sleep 5"
browser open https://m.weibo.cn
browser act kind=click ref=<avatar-ref>  // Navigate to profile

// 6. Verify post exists, then close compose tab
browser action=close targetId=<compose-tab-id>

// 7. Cleanup temporary files (if any)
// exec "rm /tmp/openclaw/uploads/*"  // Uncomment if files were uploaded
```

## Example 2: Image Post

```bash
# Prepare image
cp /path/to/image.jpg /tmp/openclaw/uploads/
```

```javascript
// 1. Open compose
browser open https://m.weibo.cn/compose

// 2. Get snapshot
browser snapshot

// 3. Type content
browser act kind=type ref=e15 text="Check out this image!"

// 4. Upload image (use upload button ref, not hidden input)
browser upload inputRef=e25 paths=["/tmp/openclaw/uploads/image.jpg"]

// 5. Wait for upload and verify visually
exec "sleep 3"
browser screenshot  // Check if image preview appears

// 6. Send
browser act kind=click ref=e10

// 7. Verify on profile page
exec "sleep 5"
browser open https://m.weibo.cn
browser act kind=click ref=<avatar-ref>

// 8. Close compose tab
browser action=close targetId=<compose-tab-id>
```

```bash
// 9. Cleanup - remove uploaded image from temp directory
rm /tmp/openclaw/uploads/image.jpg
```

## Example 3: Multiple Images

```javascript
// Upload multiple images at once
browser upload inputRef=e25 paths=[
  "/tmp/openclaw/uploads/image1.jpg",
  "/tmp/openclaw/uploads/image2.jpg",
  "/tmp/openclaw/uploads/image3.jpg"
]
```

## Important Notes

1. **File Location**: All images MUST be in `/tmp/openclaw/uploads/`
   - This is a security restriction of OpenClaw browser
   - Copy files there before upload

2. **Upload Verification**: After upload, wait 2-3 seconds and take screenshot
   - Don't check `input.files` (returns 0 even when successful)
   - Visual confirmation is reliable

3. **Post Verification**: Always verify on personal page
   - Compose page doesn't auto-redirect
   - Go to m.weibo.cn → click avatar → check latest post

4. **Close Compose Tab**: Always close compose tab after verification
   - Prevents accidental duplicate posts
   - Use `browser action=close targetId=<id>`

5. **Cleanup Temporary Files**: Temporary files are NOT automatically cleaned up
   - Remove uploaded images: `rm /tmp/openclaw/uploads/<filename>`
   - Clean old screenshots: `find ~/.openclaw/media/browser/ -type f -mtime +7 -delete`
   - **Cleanup is a required step** - always run it after publishing

## Common Element Refs (m.weibo.cn/compose)

| Element | Typical Ref | Description |
|---------|-------------|-------------|
| Text input | `e15` | textbox with placeholder "分享新鲜事…" |
| Send button | `e10` | "发送" button |
| Upload button | `e25` | Camera icon () |
| Upload button alt | `e29` | Alternative camera icon location |

**Always get fresh snapshot** - refs are dynamic and may change.

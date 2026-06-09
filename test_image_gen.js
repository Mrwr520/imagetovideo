const https = require('https');
const fs = require('fs');
const path = require('path');

const API_URL = 'https://jiuuij.de5.net/v1/images/generations';
const API_KEY = 'sk-GyiLtk9MfHxHKzv7wjmLUMeG8Vnhsw0fHPvSIK0tKK0oWDIm';

const payload = JSON.stringify({
  model: 'gpt-image-2',
  prompt: 'A cute orange cat sitting on a wooden desk next to a laptop, warm sunlight from window, photorealistic',
  n: 1,
  size: '1280x720',
  response_format: 'b64_json'
});

const url = new URL(API_URL);
const options = {
  hostname: url.hostname,
  path: url.pathname,
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload)
  }
};

console.log('Calling image generation API...');
const startTime = Date.now();

const req = https.request(options, (res) => {
  let data = '';
  res.on('data', chunk => { data += chunk; });
  res.on('end', () => {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`Status: ${res.statusCode}, Time: ${elapsed}s`);
    
    if (res.statusCode === 200) {
      try {
        const json = JSON.parse(data);
        if (json.data && json.data[0] && json.data[0].b64_json) {
          const imgBuffer = Buffer.from(json.data[0].b64_json, 'base64');
          const outPath = path.join(__dirname, 'images', `test_gen_${Date.now()}.png`);
          fs.writeFileSync(outPath, imgBuffer);
          console.log(`Image saved: ${outPath}`);
          console.log(`Image size: ${(imgBuffer.length / 1024).toFixed(1)} KB`);
        } else {
          console.log('Response keys:', Object.keys(json));
          console.log('Data:', JSON.stringify(json).substring(0, 500));
        }
      } catch (e) {
        console.log('Parse error:', e.message);
        console.log('Raw response (first 500):', data.substring(0, 500));
      }
    } else {
      console.log('Error response:', data.substring(0, 500));
    }
  });
});

req.on('error', (e) => {
  console.log('Request error:', e.message);
});

req.write(payload);
req.end();

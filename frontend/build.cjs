const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

if (fs.existsSync('../backend')) {
  const destDir = path.join(__dirname, 'api');
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  for (const file of ['main.py', 'extractor.py', 'security.py']) {
    const src = path.join(__dirname, '..', 'backend', file);
    const dest = path.join(destDir, file);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, dest);
    }
  }
}

console.log('-> VidSlide: Building frontend assets...');
execSync('npm run build', { stdio: 'inherit' });

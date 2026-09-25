const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function syncBackendFiles(srcDir, destDir) {
  if (!fs.existsSync(srcDir)) return;
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  for (const file of ['main.py', 'extractor.py', 'security.py']) {
    const srcFile = path.join(srcDir, file);
    const destFile = path.join(destDir, file);
    if (fs.existsSync(srcFile)) {
      fs.copyFileSync(srcFile, destFile);
    }
  }
}

if (fs.existsSync('frontend')) {
  console.log('-> VidSlide: Syncing backend modules to api/ and frontend/api/...');
  syncBackendFiles('backend', 'api');
  syncBackendFiles('backend', path.join('frontend', 'api'));

  console.log('-> VidSlide: Building from project root...');
  execSync('npm --prefix frontend install && npm --prefix frontend run build', { stdio: 'inherit' });

  if (fs.existsSync('frontend/dist')) {
    if (!fs.existsSync('dist')) {
      fs.mkdirSync('dist', { recursive: true });
    }
    fs.cpSync('frontend/dist', 'dist', { recursive: true });
    console.log('-> VidSlide: Successfully copied frontend/dist to ./dist');
  }
} else {
  console.log('-> VidSlide: Building inside frontend directory...');
  if (fs.existsSync('../backend')) {
    syncBackendFiles('../backend', 'api');
  }
  execSync('npm run build', { stdio: 'inherit' });
}

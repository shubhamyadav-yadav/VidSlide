const fs = require('fs');
const { execSync } = require('child_process');

if (fs.existsSync('frontend')) {
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
  execSync('npm run build', { stdio: 'inherit' });
}

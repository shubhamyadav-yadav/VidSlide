const { execSync } = require('child_process');

console.log('-> VidSlide: Building frontend assets...');
execSync('npm run build', { stdio: 'inherit' });

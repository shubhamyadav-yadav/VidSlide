/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'sans-serif'],
      },
      colors: {
        yt: {
          red: '#FF0000',
          darkRed: '#CC0000',
          brightRed: '#FF2A4D',
          rose: '#FF1E56',
          coral: '#FF4D36',
          amber: '#FF7A00',
          card: '#11131B',
          card2: '#161924',
          border: '#281D24',
          borderSoft: '#1F171D',
        },
      },
      backgroundImage: {
        'yt-gradient': 'linear-gradient(135deg, #FF0000 0%, #E62117 50%, #FF4D36 100%)',
        'yt-gradient-hover': 'linear-gradient(135deg, #FF1E27 0%, #FF0033 50%, #FF5A43 100%)',
        'yt-radial': 'radial-gradient(ellipse 70% 50% at 50% -10%, rgba(255, 0, 51, 0.22) 0%, rgba(255, 42, 77, 0.08) 50%, transparent 80%)',
        'yt-glow': 'linear-gradient(90deg, #FF0033 0%, #FF3366 50%, #FF6633 100%)',
      },
    },
  },
  plugins: [],
};

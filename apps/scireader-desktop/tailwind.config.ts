import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}', './electron/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#122033',
        muted: '#65758b',
        paper: '#f6f8fb',
        line: '#dce4ee',
        accent: '#2563eb'
      },
      boxShadow: {
        soft: '0 18px 50px rgba(15, 23, 42, 0.08)'
      }
    }
  },
  plugins: []
} satisfies Config;

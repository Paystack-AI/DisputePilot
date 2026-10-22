import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f5f7f9',
          100: '#e9edf2',
          200: '#d3dbe5',
          300: '#aebdcc',
          400: '#8298ad',
          500: '#627b92',
          600: '#4d6378',
          700: '#405161',
          800: '#374553',
          900: '#111c2b',
          950: '#080f1b',
        },
        brand: {
          50: '#eefbf4',
          100: '#d6f5e3',
          200: '#b0eacb',
          300: '#7bd9ab',
          400: '#45c087',
          500: '#20a46c',
          600: '#128357',
          700: '#106948',
          800: '#10533b',
          900: '#0e4532',
          950: '#06271d',
        },
        canvas: '#f5f6f2',
        line: '#e4e7e1',
        danger: '#dc3e42',
        warning: '#d97706',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 12px 32px -20px rgba(16, 24, 40, 0.18)',
        float: '0 20px 50px -24px rgba(8, 15, 27, 0.35)',
      },
      borderRadius: {
        '4xl': '2rem',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseRing: {
          '0%': { boxShadow: '0 0 0 0 rgba(220, 62, 66, 0.45)' },
          '70%': { boxShadow: '0 0 0 12px rgba(220, 62, 66, 0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(220, 62, 66, 0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.4s ease-out both',
        'pulse-ring': 'pulseRing 1.8s ease-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;

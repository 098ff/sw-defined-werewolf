/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      // Phase-aware palette: values come from CSS variables swapped by <html data-theme="night|day">.
      colors: {
        page: token('page'),
        panel: token('panel'),
        sunken: token('sunken'),
        line: token('line'),
        ink: token('ink'),
        muted: token('muted'),
        accent: token('accent'),
        'on-accent': token('on-accent'),
        move: token('move'),
        'move-ink': token('move-ink'),
        'move-muted': token('move-muted'),
        good: token('good'),
        bad: token('bad')
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace']
      }
    }
  },
  plugins: []
};

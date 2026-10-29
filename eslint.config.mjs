import js from '@eslint/js';
import {defineConfig} from 'eslint/config';
import globals from 'globals';

export default defineConfig([
  {
    ignores: [
      '.venv/**',
      '.pytest_cache/**',
      '.ruff_cache/**',
      '.browserrig/**',
      '**/__pycache__/**',
      'build/**',
      'dist/**',
      'node_modules/**',
    ],
  },
  js.configs.recommended,
  {
    files: ['**/*.{js,mjs}'],
    languageOptions: {ecmaVersion: 2022},
    linterOptions: {reportUnusedDisableDirectives: 'error'},
    rules: {
      curly: ['error', 'all'],
      'max-depth': ['error', 2],
      'max-nested-callbacks': ['error', 2],
      'no-else-return': ['error', {allowElseIf: false}],
      'no-nested-ternary': 'error',
      'prefer-const': 'error',
      eqeqeq: ['error', 'always'],
    },
  },
  {
    files: ['browserrig/**/scripts/*.js'],
    languageOptions: {sourceType: 'script', globals: globals.browser},
    // CDP receives each file as a standalone function declaration.
    rules: {'no-unused-vars': ['error', {varsIgnorePattern: '^browserrig'}]},
  },
  {
    files: ['**/*.mjs'],
    languageOptions: {globals: globals.node},
  },
]);

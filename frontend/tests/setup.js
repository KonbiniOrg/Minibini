// Registers @testing-library/jest-dom matchers (toBeInTheDocument,
// toHaveAttribute, …) on expect, globally for every test file.
// Component cleanup between tests is handled automatically by the
// svelteTesting() plugin in vitest.config.js.
import '@testing-library/jest-dom';

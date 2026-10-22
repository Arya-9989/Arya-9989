// SVGO 4 config for the profile artwork.
// Keeps <title>, role, viewBox and ids (aria-labelledby, gradients), and disables passes that
// would break the responsive layouts: inlined styles would beat the @media rules, and
// converting <rect> to <path> would drop the CSS `rx` override used on phones.
export default {
  multipass: true,
  plugins: [
    {
      name: 'preset-default',
      params: {
        overrides: {
          inlineStyles: false,
          convertShapeToPath: false,
          cleanupIds: false,
          removeUnknownsAndDefaults: { keepRoleAttr: true, keepAriaAttrs: true },
        },
      },
    },
  ],
};

/* Queuer field presets: the single place that defines fields, types and validation.
   Used by BOTH the dashboard (choosing fields) and the join page (filling them). */
(function (global) {
  "use strict";

  const squash = (s) => String(s ?? "").trim().replace(/\s+/g, " ");
  const compactUpper = (s) => String(s ?? "").replace(/\s+/g, "").toUpperCase();

  // type -> how to clean the value, how to check it, and which input attributes to use
  const TYPES = {
    text: {
      normalize: squash,
      check: (v) => v.length <= 100 || "is too long",
      attrs: { type: "text", maxlength: "100" },
    },
    name: {
      normalize: squash,
      check: (v) =>
        (v.length <= 60 && /^[\p{L}\p{M}]+(?:[ .'\-]+[\p{L}\p{M}]+)*\.?$/u.test(v)) || "must contain letters only",
      attrs: { type: "text", maxlength: "60", autocomplete: "name" },
    },
    roll: {
      normalize: compactUpper,
      check: (v) =>
        (/^[A-Z0-9]{1,30}$/.test(v) && /\d/.test(v)) || "must be letters/numbers with at least one digit (e.g. 21CS01)",
      attrs: { type: "text", maxlength: "30", autocapitalize: "characters", autocomplete: "off" },
    },
    code: {
      normalize: compactUpper,
      check: (v) => /^[A-Z0-9]{1,30}$/.test(v) || "must contain only letters and numbers",
      attrs: { type: "text", maxlength: "30", autocapitalize: "characters", autocomplete: "off" },
    },
    phone: {
      normalize: (s) => String(s ?? "").replace(/[\s\-().]/g, ""),
      check: (v) => /^\+?\d{7,15}$/.test(v) || "must be a valid phone number (7-15 digits)",
      attrs: { type: "tel", inputmode: "tel", maxlength: "20", autocomplete: "tel" },
    },
  };

  // The only fields a teacher can pick. Edit this list to add/remove options.
  const LIST = [
    { key: "name",     label: "Name",        type: "name",  hint: "letters only",            on: true  },
    { key: "roll",     label: "Roll No.",    type: "roll",  hint: "e.g. 21CS01",             on: true  },
    { key: "class",    label: "Class / Std", type: "code",  hint: "e.g. 10, FYBSC",          on: false },
    { key: "division", label: "Division",    type: "code",  hint: "e.g. A, B",               on: false },
    { key: "phone",    label: "Phone",       type: "phone", hint: "digits only",             on: false },
  ];

  // Old queues (or unknown labels) safely fall back to plain text.
  const typeFor = (label) => (LIST.find((p) => p.label === label) || {}).type || "text";

  function applyAttrs(input, label) {
    const t = TYPES[typeFor(label)];
    Object.entries(t.attrs).forEach(([k, v]) => input.setAttribute(k, v));
  }

  // Validate one value -> { value, error }
  function checkOne(label, raw) {
    const t = TYPES[typeFor(label)];
    const value = t.normalize(raw);
    if (!value) return { value, error: `${label} is required` };
    const res = t.check(value);
    return res === true ? { value } : { value, error: `${label} ${res}` };
  }

  // Validate everything for a queue -> { data, errors:{label:message} }
  function validate(queue, values) {
    const data = {};
    const errors = {};
    queue.fields.forEach((label) => {
      const { value, error } = checkOne(label, values[label]);
      if (error) errors[label] = error;
      else data[label] = value;
    });
    return { data, errors };
  }

  global.QueuerPresets = { LIST, typeFor, applyAttrs, checkOne, validate };
})(window);

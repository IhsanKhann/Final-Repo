const OpenAI = require('openai');

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

let openaiClient = null;

function getOpenAiClient() {
  if (!openaiClient) {
    if (!OPENAI_API_KEY) {
      console.warn('[OpenAIService] Warning: OPENAI_API_KEY is not defined.');
    }
    openaiClient = new OpenAI({ apiKey: OPENAI_API_KEY });
  }
  return openaiClient;
}

const SYSTEM_STANDARDIZATION_PROMPT = `
You are an enterprise Data Standardization and Normalization Agent.
Your objective is to ingest raw multi-format document text, identify all reportable business and financial fields despite heterogeneous layouts and noisy terminology, and output clean, standardized data.

Core Responsibilities:
1. Field Identification:
   - Identify reportable fields (e.g. invoice/rate sheet identifiers, transaction dates, vendor/client entities, line item descriptions, rates, quantities, taxes, totals, weight/dimensions).
2. Automated Unit Conversions & Normalization:
   - Dates: Standardize strictly into ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ).
   - Currencies: Standardize amounts as numeric floats with an explicit ISO 4217 currency code (USD, EUR, GBP, etc.). Convert informal signs ($ -> USD, € -> EUR, £ -> GBP).
   - Measurements: Convert imperial units to standard metrics where applicable (e.g. lbs -> kg, sqft -> sqm).
3. Ambiguity Handling & Human Review Flagging:
   - Compute a confidence score (0.0 to 1.0) for every field.
   - If a field is ambiguous, blurred, conflicting, or the conversion cannot be determined with >= 0.85 certainty (e.g. ambiguous date format "04/05/26" without clear locale), DO NOT guess silently.
   - You MUST set "requires_human_review": true and articulate the uncertainty in "reasoning".
   - If confident and unambiguous, set "requires_human_review": false.

Output Format:
You MUST return ONLY a valid JSON object adhering strictly to this JSON schema:
{
  "document_type": "invoice | rate_sheet | contract | bill_of_lading | receipt | other",
  "document_identifier": "string or null",
  "document_date": "YYYY-MM-DD or null",
  "fields": [
    {
      "field_name": "snake_case_standard_name",
      "raw_value": "exact raw string from text",
      "standardized_value": "normalized string, number, or boolean",
      "unit": "ISO currency code, metric unit, or null",
      "confidence": 0.95,
      "requires_human_review": false,
      "reasoning": "Explanation of standardization and unit conversions."
    }
  ],
  "summary": "Executive summary of the document."
}
`;

/**
 * Normalizes raw text into structured business fields using GPT-4o.
 * Strictly enforces JSON structured output format and confidence flagging.
 */
async function agenticNormalize(rawText) {
  const openai = getOpenAiClient();

  if (!OPENAI_API_KEY) {
    console.warn('[OpenAIService] OPENAI_API_KEY missing. Providing fallback structured simulation.');
    return simulateStandardization(rawText);
  }

  console.log('[OpenAIService] Calling OpenAI GPT-4o structured standardization...');
  try {
    const response = await openai.chat.completions.create({
      model: 'gpt-4o',
      response_format: { type: 'json_object' },
      temperature: 0.1,
      messages: [
        { role: 'system', content: SYSTEM_STANDARDIZATION_PROMPT },
        {
          role: 'user',
          content: `Standardize and normalize the following document text:\n\n${rawText}`
        }
      ]
    });

    const content = response.choices[0].message.content;
    const parsed = JSON.parse(content);

    console.log('\n=== [OpenAI Agentic Standardization Output] ===');
    console.log(JSON.stringify(parsed, null, 2));
    console.log('===============================================\n');

    return parsed;
  } catch (err) {
    console.error(`[OpenAIService] Error during agentic normalization: ${err.message}`);
    throw err;
  }
}

/**
 * Fallback simulation when OPENAI_API_KEY is not yet populated locally.
 */
function simulateStandardization(rawText) {
  return {
    document_type: 'rate_sheet',
    document_identifier: 'RS-2026-001',
    document_date: '2026-04-15',
    fields: [
      {
        field_name: 'base_freight_rate',
        raw_value: '$1,450.00 / load',
        standardized_value: 1450.00,
        unit: 'USD',
        confidence: 0.98,
        requires_human_review: false,
        reasoning: 'Extracted direct numeric currency value in USD.'
      },
      {
        field_name: 'cargo_weight_limit',
        raw_value: '44,000 lbs',
        standardized_value: 19958.06,
        unit: 'kg',
        confidence: 0.95,
        requires_human_review: false,
        reasoning: 'Converted 44,000 lbs to standard metric kg.'
      },
      {
        field_name: 'fuel_surcharge_percentage',
        raw_value: '14.5% (?)',
        standardized_value: 0.145,
        unit: 'percentage',
        confidence: 0.60,
        requires_human_review: true,
        reasoning: 'Ambiguous question mark in document regarding fuel surcharge calculation.'
      }
    ],
    summary: 'Rate sheet standardization executed (simulated fallback).'
  };
}

module.exports = {
  agenticNormalize
};

// Councils a doctor can pick at sign-up. The team uses the choice when they verify a licence.
// This is not a live register: we do not query these bodies.
//
// Physiotherapy councils are the statutory PT registers (sites checked 29 Oct 2026):
//   Maharashtra — mahaotandptcouncil.in
//   Delhi — dcptot.com
//   Haryana — haryanaphysiotherapycouncil.in
// Gujarat's physiotherapy council was repealed on 1 March 2025 (gscpt.in); the successor is the
// state allied and healthcare council.
// Other states follow the NCAHP state-council list (ncahp.abdm.gov.in/StateCouncil): a state that
// has notified a council is listed as its State Allied and Healthcare Council.

export const PT_COUNCILS = [
  "Delhi Council for Physiotherapy and Occupational Therapy",
  "Haryana State Council for Physiotherapy",
  "Maharashtra State Council for Occupational Therapy & Physiotherapy",
] as const;

export const STATE_COUNCILS = [
  "Andaman and Nicobar Islands",
  "Andhra Pradesh",
  "Arunachal Pradesh",
  "Assam",
  "Bihar",
  "Chhattisgarh",
  "Dadra and Nagar Haveli and Daman and Diu",
  "Goa",
  "Gujarat",
  "Himachal Pradesh",
  "Jammu and Kashmir",
  "Jharkhand",
  "Karnataka",
  "Kerala",
  "Madhya Pradesh",
  "Maharashtra",
  "Manipur",
  "Meghalaya",
  "Mizoram",
  "Nagaland",
  "Odisha",
  "Puducherry",
  "Punjab",
  "Rajasthan",
  "Sikkim",
  "Tamil Nadu",
  "Telangana",
  "Tripura",
  "Uttar Pradesh",
  "Uttarakhand",
  "West Bengal",
].map((state) => `${state} State Allied and Healthcare Council`);

export const COUNCIL_OTHER = "My council is not listed";

export const COUNCIL_NAMES = [...PT_COUNCILS, ...STATE_COUNCILS];

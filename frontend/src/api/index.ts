// 프런트의 API 경계는 이 폴더 하나다(generated/는 `npm run gen:api`로 backend/openapi.json에서 생성).
export * from "./types";
export { api } from "./endpoints";
export { ApiError, errorMessage, clearApiCache, API_PREFIX, AUTH_LOST_EVENT, requestPage } from "./client";

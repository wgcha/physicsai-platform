backend/openapi.json 생성 후:
  npx openapi-typescript ../../../backend/openapi.json -o schema.d.ts
그 다음 ../types.ts의 인터페이스를 components["schemas"][...] 별칭으로 교체한다.

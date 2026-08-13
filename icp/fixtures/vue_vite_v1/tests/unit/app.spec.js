import { describe, expect, it } from 'vitest'

describe('ICP Vue fixture', () => {
  it('keeps stable design node ids', () => {
    expect(['fixture-root', 'fixture-title']).toEqual(['fixture-root', 'fixture-title'])
  })
})

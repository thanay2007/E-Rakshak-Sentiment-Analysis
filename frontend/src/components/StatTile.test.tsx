import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StatTile from './StatTile';
import { Activity } from 'lucide-react';

describe('StatTile Component', () => {
  it('renders label and value correctly', async () => {
    render(<StatTile label="Posts Monitored" value={1000} icon={Activity} />);
    expect(screen.getByText('Posts Monitored')).toBeInTheDocument();
    // The value counts up from 0 via GSAP (1.1s), so wait for the final figure.
    expect(await screen.findByText('1,000', {}, { timeout: 3000 })).toBeInTheDocument();
  });
});
